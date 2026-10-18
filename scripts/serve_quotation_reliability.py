"""Serve the verified v2 release desk on this computer."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend/src'))
import uvicorn
from demopilot.quotation_api import create_app

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--registry',required=True,type=Path);p.add_argument('--port',default=5188,type=int);a=p.parse_args()
    uvicorn.run(create_app(a.registry),host='127.0.0.1',port=a.port,log_level='warning')
