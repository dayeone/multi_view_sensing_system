#!/usr/bin/env python3
"""focus_finder.py의 sharpness.csv를 그래프(PNG)로 그린다.

[사용법]
  python3 quick_capture/plot_focus_sweep.py cam1            # 카메라 1대
  python3 quick_capture/plot_focus_sweep.py cam1 cam2 cam4   # 여러 대 (개별 + 비교 그래프)
"""
import csv
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def load_csv(cam_name):
    path = os.path.join("focus_scan", cam_name, "sharpness.csv")
    focus, sharp = [], []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            focus.append(int(row["focus"]))
            sharp.append(float(row["sharpness"]))
    return focus, sharp


def plot_single(cam_name):
    focus, sharp = load_csv(cam_name)

    fig, ax = plt.subplots()
    ax.plot(focus, sharp, marker="o")
    ax.set_title(f"focus vs sharpness ({cam_name})")
    ax.set_xlabel("focus (0=far, 255=near)")
    ax.set_ylabel("sharpness")
    ax.grid(True)

    out_path = os.path.join("focus_scan", cam_name, "sharpness.png")
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def plot_combined(cam_names):
    fig, ax = plt.subplots()
    for cam_name in cam_names:
        focus, sharp = load_csv(cam_name)
        ax.plot(focus, sharp, marker="o", label=cam_name)
    ax.set_title(f"focus vs sharpness ({cam_names[0]}-{cam_names[-1]})")
    ax.set_xlabel("focus (0=far, 255=near)")
    ax.set_ylabel("sharpness")
    ax.grid(True)
    ax.legend()

    out_path = os.path.join("focus_scan", "sharpness_compare.png")
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


if __name__ == "__main__":
    cams = sys.argv[1:]
    if not cams:
        print("사용법: python3 plot_focus_sweep.py cam1 [cam2 ...]")
        sys.exit(1)

    for cam in cams:
        path = plot_single(cam)
        print(f"저장: {path}")

    if len(cams) > 1:
        path = plot_combined(cams)
        print(f"저장: {path}")
