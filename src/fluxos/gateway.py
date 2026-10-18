"""Single deterministic FLUX publication gateway.

Model output proposes candidate files. The gateway handles dependency freshness,
source snapshot identity, generation fencing and external acceptance evidence. No
second LLM supervisor decides safety. This checks mediated inputs only.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable
import shutil
import uuid
from .kernel import Memory, Principal, Stale, Denied, IntegrityError

if TYPE_CHECKING:
    from .agent import Workspace
    from .kernel import Observation


@dataclass(frozen=True)
class GateOutcome:
    decision: str
    status: str
    reason: str
    published_snapshot: dict | None = None
    draft_snapshot: dict | None = None
    verification: dict | None = None


class UnifiedGate:
    """One publication boundary; never runs the model or tests itself."""
    def __init__(self, memory: Memory, actor: Principal):
        self.memory=memory
        self.actor=actor

    def publish(self, *, candidate: Workspace, baseline: Workspace | None,
                base_manifest: dict[str,str], observation: Observation,
                developer: dict, acceptance: dict, model: str, calls: int,
                output_id: str, job_id: str | None, generation: int | None,
                project_id: str | None = None, base_revision: int | None = None,
                trusted_acceptance: Callable[[Workspace], dict] | None = None) -> GateOutcome:
        """Seal -> verify the seal -> validate witnesses -> publish that same seal.

        Only a trusted in-process operator can inject the acceptance callback.
        Network clients never supply it. A PASS dictionary alone is insufficient.
        Developer tests are diagnostic, not publication authorization.
        """
        try:
            manifest=candidate.file_manifest()
        except (ValueError, OSError) as exc:
            return GateOutcome('REJECT','COMMIT_REJECTED',f'Unsafe candidate workspace: {str(exc)[:160]}')
        if not manifest:
            return GateOutcome('CONTINUE_PRIVATE','INCOMPLETE','No candidate files')
        root=candidate.path.parent
        root_store=root/'.fluxos-sealed'
        root_store.mkdir(parents=True,exist_ok=True)
        dest=root_store/uuid.uuid4().hex
        retained=False
        try:
            sealed=type(candidate)(dest)
            copied=candidate.snapshot_to(sealed)
            # Detect any modifications during copying, including a changed source.
            if candidate.file_manifest()!=manifest or copied!=manifest or sealed.file_manifest()!=manifest:
                raise IntegrityError('candidate changed while sealing snapshot')
            # Seal first, never evaluate the mutable workspace. Disable modifications
            # by ordinary worker UIDs. A privileged host attacker remains out of scope.
            for path in sealed.path.rglob('*'):
                if path.is_file(): path.chmod(0o444)
            for path in sorted((x for x in sealed.path.rglob('*') if x.is_dir()),key=lambda x:len(x.parts),reverse=True):
                path.chmod(0o555)
            sealed.path.chmod(0o555)
            if baseline is not None and baseline.file_manifest()!=base_manifest:
                raise Stale('input source changed before verification')
            # This callable executes independently supplied black-box acceptance on
            # the immutable snapshot. Old acceptance dicts are ignored for trust.
            evidence=(trusted_acceptance(sealed) if trusted_acceptance else
                      {'status':'NOT_CONFIGURED','reason':'No trusted acceptance callback'})
            if not isinstance(evidence,dict):
                raise IntegrityError('invalid acceptance result')
            if sealed.file_manifest()!=manifest:
                raise IntegrityError('sealed candidate changed during acceptance')
            if baseline is not None and baseline.file_manifest()!=base_manifest:
                raise Stale('input source changed during acceptance')
            contract_path=evidence.get('contract_path')
            if contract_path is not None:
                try:
                    from pathlib import Path as _Path
                    import hashlib as _hashlib
                    current_contract=_hashlib.sha256(_Path(contract_path).read_bytes()).hexdigest()
                except (OSError,TypeError,ValueError) as exc:
                    raise Stale('operator acceptance contract unavailable') from exc
                if current_contract!=evidence.get('contract_hash'):
                    raise Stale('operator acceptance contract changed after testing')
            witnesses=observation.manifest()
            self.memory.validate_manifest(self.actor,witnesses)
            # Only a black-box verifier with a matching candidate hash, a contract
            # hash and at least one independently judged case can publish.
            verified=(evidence.get('status')=='PASS' and
                      type(evidence.get('test_count')) is int and evidence['test_count']>0 and
                      evidence.get('trust_boundary')=='blackbox' and
                      isinstance(evidence.get('contract_hash'),str) and
                      len(evidence['contract_hash'])>=1 and
                      evidence.get('candidate_manifest_hash')==sealed.manifest_digest())
            sealed_digest=sealed.manifest_digest()
            if verified:
                # Kernel code expects published store to have this fixed name.
                published_root=root/'.fluxos-published'
                published_root.mkdir(parents=True,exist_ok=True)
                published=published_root/dest.name
                # Rename between trusted-store siblings without copying bytes.
                # If an attacker tampers with the published tree, kernel's
                # verification checks its hashes again within the DB transaction.
                # POSIX requires write permission on a directory when moving it
                # between parents (its '..' entry changes). Keep every file and
                # child directory sealed; restore the root before revalidation.
                dest.chmod(0o755)
                dest=dest.rename(published)
                dest.chmod(0o555)
                if type(candidate)(dest).file_manifest()!=manifest:
                    raise IntegrityError('published snapshot changed before commit')
                value={'files':list(manifest),'tests':developer.get('status'),
                       'test_count':developer.get('test_count',0),
                       'acceptance':evidence,'model':model,'calls':calls,
                       'snapshot':str(dest.resolve()),'file_hashes':manifest,
                       'independent_acceptance':True,
                       'accepted_candidate_hash':sealed_digest,
                       'accepted_contract_hash':evidence['contract_hash']}
                version=self.memory.put_artifact(self.actor,output_id,value,witnesses,
                                                  job_id=job_id,job_generation=generation,
                                                  project_id=project_id,expected_project_revision=base_revision)
                retained=True
                return GateOutcome('COMMIT','VERIFIED','Sealed candidate independently accepted',
                                   published_snapshot={'id':output_id,'version':version,
                                      'path':str(dest.resolve()),'file_hashes':manifest},
                                   verification=evidence)
            # Non-accepted results remain private drafts, not published artifacts.
            draft_root=root/'.fluxos-drafts'
            draft_root.mkdir(parents=True,exist_ok=True)
            draft=draft_root/dest.name
            dest.chmod(0o755)
            dest=dest.rename(draft)
            dest.chmod(0o555)
            retained=True
            return GateOutcome('CONTINUE_PRIVATE','DRAFT',
                               'Independent acceptance not satisfied: '+str(evidence.get('status','unknown')),
                               draft_snapshot={'path':str(dest.resolve()),'file_hashes':manifest,
                                               'status':'UNVERIFIED_DRAFT'},verification=evidence)
        except Stale as exc:
            return GateOutcome('REPAIR','STALE_REJECTED',str(exc))
        except (Denied,IntegrityError,ValueError,OSError) as exc:
            return GateOutcome('REJECT','COMMIT_REJECTED',f'{type(exc).__name__}: {str(exc)[:200]}')
        except Exception as exc:
            return GateOutcome('REJECT','COMMIT_REJECTED',f'{type(exc).__name__}: {str(exc)[:160]}')
        finally:
            if not retained:
                # Remove even readonly files created by the seal operation.
                if dest.exists():
                    for path in [dest,*dest.rglob('*')]:
                        try:
                            # Windows also requires clearing the read-only bit
                            # on files before unlinking a rejected snapshot.
                            if not path.is_symlink():
                                path.chmod(0o755 if path.is_dir() else 0o644)
                        except OSError:pass
                    shutil.rmtree(dest,ignore_errors=True)
