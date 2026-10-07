# Particle DRR Visualization｜颗粒识别与除尘率可视化

Reproducible particle coverage tracking and dust removal rate (DRR) visualization from video or image frames.

从视频或按顺序命名的图像帧中识别颗粒覆盖面积，逐帧计算尘埃去除率 DRR，并输出首末帧对比图、识别 GIF 和 CSV。核心方法来自压缩包中的 `10sdDRR.py`：灰度增强、首帧分位阈值、固定 ROI、前 10 秒逐帧统计。`drr.py` 整理了输入和输出接口，并修正了原脚本把所有视频强制截为 `30×10` 帧等边界问题。

## 用示例运行

安装依赖：`python -m pip install -r requirements.txt`

在项目目录运行：

```powershell
python examples/generate_demo_frames.py
python drr.py --input examples/synthetic_frames --roi-mask examples/synthetic_roi_mask.png --fps 10 --seconds 3 --output results/demo --save-gif
```

示例中绿色颗粒随帧数减少，**全部图像由程序合成，仅用于展示操作，不代表实验结果**。查看 `results/demo/metrics.csv`、`first_last_comparison.png` 和 `recognition_preview.gif`。

![合成示例的首末帧识别对比](examples/expected/first_last_comparison.png)

## 换成自己的数据

```powershell
python drr.py --input "D:/你的实验/视频.mp4" --roi-mask "D:/你的实验/roi_mask.png" --output results/experiment --save-gif
```

ROI 掩膜必须与视频帧尺寸相同；白色为统计区域，黑色不计入。若没有掩膜，程序暂用首帧的非黑像素作为 ROI，这只适合已遮罩的视频。视频 FPS 由文件读取；图像帧文件夹要用 `--fps` 指定实际采样率。默认分析前 10 秒，可用 `--seconds` 调整。

定义：`R_t = 识别为颗粒的 ROI 像素数 / ROI 像素总数`，`DRR_t=(R_0-R_t)/R_0`，`CRR_t=1-R_t`。如果首帧无颗粒，DRR 留空，因为分母为零。阈值以首帧计算并保持不变；真实视频的光照变化、反光和遮挡可能影响识别，公开论文数据前需要人工核验。

## 版本取舍

`drr.py` 基于原 `10sdDRR.py` 的逐帧灰度路线整理。主项目没有收录旧测试版、原版副本和未接入主流程的 HSV 工具；原始文件由作者保留。示例帧由 `examples/generate_demo_frames.py` 生成，因此仓库只保存生成器和少量预览结果。

## 需要补充的真实材料

一段允许公开的短视频、对应的 ROI 掩膜、实际 FPS，以及少量人工核对的首末帧颗粒覆盖率。用这些材料才能验证 DRR 数值，并制作可信的 GitHub 展示图。
