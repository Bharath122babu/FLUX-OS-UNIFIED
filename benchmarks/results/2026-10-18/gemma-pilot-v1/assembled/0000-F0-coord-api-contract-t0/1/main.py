import pathlib, subprocess, sys
base=pathlib.Path(__file__).resolve().parent
data=sys.stdin.read()
for name in ("engine.py", "formatter.py"):
    process=subprocess.run([sys.executable, "-I", "-B", str(base/name)], input=data, capture_output=True, text=True)
    if process.returncode:
        sys.stderr.write(process.stderr)
        sys.exit(process.returncode)
    data=process.stdout
sys.stdout.write(data)
