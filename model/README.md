---
base_model:
- nvidia/stt_en_fastconformer_transducer_large
library_name: nemo
license: cc-by-4.0
tags:
- pytorch
- NeMo
arxiv: 2601.13044
pipeline_tag: automatic-speech-recognition
language:
- th
---

# Typhoon-asr-realtime

<style>
img {
 display: inline;
}
</style>

| [![Model architecture](https://img.shields.io/badge/Model_Arch-FastConformer--Transducer-lightgrey#model-badge)](#model-architecture)
| [![Model size](https://img.shields.io/badge/Params-114M-lightgrey#model-badge)](#model-architecture)
| [![Language](https://img.shields.io/badge/Language-th-lightgrey#model-badge)](#datasets)
| [![arXiv](https://img.shields.io/badge/arXiv-2601.13044-b31b1b.svg)](https://arxiv.org/abs/2601.13044)

**Typhoon ASR Real-Time** is a next-generation, open-source Automatic Speech Recognition (ASR) model built specifically for real-world streaming applications in the Thai language. It is designed to deliver fast and accurate transcriptions while running efficiently on standard CPUs. This enables users to host their own ASR service, reducing costs and avoiding the need to send sensitive data to third-party cloud services.
The model is trained on 10,000 hours of Thai audio transcriptions to help it generalize to any environments.

The model is based on [NVIDIA's FastConformer Transducer model](https://docs.nvidia.com/deeplearning/nemo/user-guide/docs/en/main/asr/models.html#fast-conformer), which is optimized for low-latency, real-time performance.

By using this model, you agree to the OpenTyphoon Terms and Conditions and acknowledge the Privacy Notice: https://opentyphoon.ai/tac · https://opentyphoon.ai/privacy

**Project Page:** [https://opentyphoon.ai/model/typhoon-asr-realtime](https://opentyphoon.ai/model/typhoon-asr-realtime)

**Try our demo available on [Demo]()**

**Code / Examples available on [Github](https://github.com/scb-10x/typhoon-asr)**

**Release Blog available on [OpenTyphoon Blog](https://opentyphoon.ai/blog/en/typhoon-asr-realtime-release)**

***

### Performance

<img src="https://storage.googleapis.com/typhoon-public/assets/typhoon_asr/performance-typhoon-asr-realtime.png" alt="cer vs rtfx performance" width="90%"/>

### Summary of Findings

**Typhoon ASR Realtime** achieves 4097x real-time processing speed with competitive accuracy **(CER: 0.0984)**, representing a 6x throughput improvement over the next fastest model. RTFx values are from the [Open ASR Leaderboard on Hugging Face](https://huggingface.co/spaces/hf-audio/open_asr_leaderboard). The model outperforms Whisper variants by 15-19x in throughput while maintaining comparable accuracy, making it ideal for production Thai speech recognition requiring real-time performance and high-volume processing scenarios.
***

### Usage and Implementation

**(Recommended): Quick Start with Google Colab**

For a hands-on demonstration without any local setup, you can run this project directly in Google Colab. The notebook provides a complete environment to transcribe audio files and experiment with the model.

[![Alt text](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/drive/1t4tlRTJToYRolTmiN5ZWDR67ymdRnpAz?usp=sharing)

**(Recommended): Using the `typhoon-asr` Package**

This is the easiest way to get started. You can install the package via pip and use it directly from the command line or within your Python code.

**1. Install the package:**
```bash
pip install typhoon-asr
```

**2. Command-Line Usage:**
```bash
# Basic transcription (auto-detects device)
typhoon-asr path/to/your_audio.wav

# Transcription with timestamps on a specific device
typhoon-asr path/to/your_audio.mp3 --with-timestamps --device cuda
```

**3. Python API Usage:**
```python
from typhoon_asr import transcribe

# Basic transcription
result = transcribe("path/to/your_audio.wav")
print(result['text'])

# Transcription with timestamps
result_with_timestamps = transcribe("path/to/your_audio.wav", with_timestamps=True)
print(result_with_timestamps)
```

**(Alternative): Running from the Repository Script**

You can also run the model by cloning the repository and using the inference script directly. This method is useful for development or if you need to modify the underlying code.

**1. Clone the repository and install dependencies:**
```bash
git clone https://github.com/scb-10x/typhoon-asr.git
cd typhoon-asr
pip install -r requirements.txt
```

**2. Run the inference script:**
The `typhoon_asr_inference.py` script handles audio resampling and processing automatically.

```bash
# Basic Transcription (CPU):
python typhoon_asr_inference.py path/to/your_audio.m4a

# Transcription with Estimated Timestamps:
python typhoon_asr_inference.py path/to/your_audio.wav --with-timestamps

# Transcription on a GPU:
python typhoon_asr_inference.py path/to/your_audio.mp3 --device cuda
```
## Citation

If you use this model in your research or application, please cite our technical report:

```bibtex
@misc{warit2026typhoonasr,
      title={Typhoon ASR Real-time: FastConformer-Transducer for Thai Automatic Speech Recognition}, 
      author={Warit Sirichotedumrong and Adisai Na-Thalang and Potsawee Manakul and Pittawat Taveekitworachai and Sittipong Sripaisarnmongkol and Kunat Pipatanakul},
      year={2026},
      eprint={2601.13044},
      archivePrefix={arXiv},
      primaryClass={cs.CL},
      url={https://arxiv.org/abs/2601.13044}, 
}
```
## **Follow us**

**https://twitter.com/opentyphoon**

## **Support**

**https://discord.gg/us5gAYmrxw**