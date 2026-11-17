"""Apply auditable patches to pinned upstream peripheral sources.

Renode's supported ad-hoc C# compiler builds these as separate model types;
the stock binary and its CPU/native execution engine remain untouched.
"""
import hashlib
from pathlib import Path
import shutil
import subprocess

HERE=Path(__file__).resolve().parent
OUT=HERE/'out'
OUT.mkdir(exist_ok=True)
hashes={
 'STM32_Timer.cs':'7e99f48c1daae8c1f2e4eef22eb09617b96f0abf61be13b2bec4d96f1e7b328d',
 'STM32F4_RCC.cs':'ac5935ad06b4379fea8b3c9662e9447fe8a5b0aba7837795ad92e05d04a855c3',
}
for name,digest in hashes.items():
    source=HERE/'upstream'/name
    if hashlib.sha256(source.read_bytes()).hexdigest()!=digest:
        raise RuntimeError(f'pinned upstream source checksum mismatch: {name}')
    shutil.copyfile(source,OUT/name)
for patch in sorted((HERE/'patches').glob('*.patch')):
    subprocess.run(['patch','--batch','--fuzz=0','-p0','-i',str(patch)],cwd=OUT,check=True)
# Mechanical type renaming avoids duplicate types in Infrastructure.dll. It is
# deliberately separate from semantic patches, which can be reviewed upstream.
for name,renamed in [('STM32_Timer','QualifiedSTM32Timer'),('STM32F4_RCC','QualifiedSTM32RCC')]:
    text=(OUT/(name+'.cs')).read_text(encoding='utf-8-sig')
    text=text.replace('STM32_Timer','QualifiedSTM32Timer').replace('STM32F4_RCC','QualifiedSTM32RCC')
    (OUT/(renamed+'.cs')).write_text(text)
shutil.copyfile(HERE/'STM32AFInput.cs',OUT/'STM32AFInput.cs')
