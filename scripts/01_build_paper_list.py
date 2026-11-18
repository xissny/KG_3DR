"""阶段1：扫描PDF并生成清单；人工核对元数据后再抽取。"""
import argparse
from pathlib import Path
from _bootstrap import finish
from src.papers.pipeline import build_paper_list

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--pdf-dir', type=Path, help='PDF目录，默认data/pdfs')
args = parser.parse_args()
finish(build_paper_list, pdf_dir=args.pdf_dir)
