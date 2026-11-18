"""根据当前正式数据生成报告、可编辑PPT、PDF与讲稿；缺失结果明确标记。"""
import argparse
from _bootstrap import finish
from src.common.deliverables import build_materials
parser = argparse.ArgumentParser(description=__doc__)
parser.parse_args()
finish(build_materials)
