"""Compile bridge; optional atomic install with a recoverable backup. No game launch."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--game',type=Path,default=Path(r'D:\steam\steamapps\common\Hollow Knight'))
    parser.add_argument('--install',action='store_true')
    args=parser.parse_args(); managed=args.game/'hollow_knight_Data/Managed'; core=args.game/'BepInEx/core'
    output=ROOT/'artifacts/build/PantheonTraining.dll';output.parent.mkdir(parents=True,exist_ok=True)
    refs=[managed/x for x in ['Assembly-CSharp.dll','Assembly-CSharp-firstpass.dll','PlayMaker.dll','UnityEngine.dll','UnityEngine.CoreModule.dll','UnityEngine.Physics2DModule.dll','netstandard.dll']]
    refs += [core/x for x in ['BepInEx.dll','0Harmony.dll']]
    subprocess.run([r'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe','/nologo','/target:library','/out:'+str(output)]+['/reference:'+str(p) for p in refs]+[str(ROOT/'mod'/n) for n in ['TrainingBridge.cs','MantisTelemetry.cs','TrainingCurriculumProfile.cs','FalseKnightAudit.cs','HornetTelemetry.cs']],check=True)
    if args.install:
        dest=args.game/'BepInEx/plugins/PantheonTraining.dll'
        backup=ROOT/'artifacts/hornet-install-backup/PantheonTraining.dll';backup.parent.mkdir(parents=True,exist_ok=True)
        if dest.exists() and not backup.exists():shutil.copyfile(dest,backup)
        temp=dest.with_suffix('.candidate');shutil.copyfile(output,temp);os.replace(temp,dest)
    print(output)

if __name__=='__main__':main()
