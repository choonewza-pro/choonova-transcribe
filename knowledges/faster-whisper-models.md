# Faster-Whisper Model Sizes and Specifications

เอกสารสรุปขนาดและประเภทของโมเดล `faster-whisper` (CTranslate2) ทั้งหมดที่มีใน Built-in Registry รวมถึงรายละเอียดจำนวน Parameter, VRAM และคำแนะนำในการใช้งาน

---

## 1. Standard Whisper Models (รุ่นมาตรฐาน)

โมเดลหลักจาก OpenAI ที่ถูกแปลงโครงสร้างสำหรับ CTranslate2 แบ่งออกเป็นแบบ **Multilingual** (รองรับหลายภาษารวมถึงภาษาไทย `th`) และแบบ **`.en`** (เฉพาะภาษาอังกฤษ)

| ขนาดโมเดล (Size) | ชื่อ Model ID | จำนวน Parameters | VRAM โดยประมาณ (FP16) | หมายเหตุ |
| :--- | :--- | :--- | :--- | :--- |
| **Tiny** | `tiny`, `tiny.en` | ~39M | ~1 GB | เหมาะสำหรับอุปกรณ์ทรัพยากรต่ำ |
| **Base** | `base`, `base.en` | ~74M | ~1 GB | สมดุลความเร็วสำหรับข้อความสั้น |
| **Small** | `small`, `small.en` | ~244M | ~2 GB | เริ่มประมวลผลภาษาไทยได้พอใช้ |
| **Medium** | `medium`, `medium.en` | ~769M | ~3-4 GB | ความแม่นยำดี เหมาะสำหรับหลายภาษา |
| **Large-v1** | `large-v1` | ~1550M | ~5 GB | Large รุ่นแรก |
| **Large-v2** | `large-v2` | ~1550M | ~5 GB | ปรับปรุงความแม่นยำจาก v1 |
| **Large-v3** | `large-v3` *(alias: `large`)* | ~1550M | ~5 GB | รุ่นแม่นยำที่สุดสำหรับหลายภาษา |

---

## 2. Turbo Model (รุ่นเน้นความเร็ว)

* **`turbo`** หรือ **`large-v3-turbo`** (~809M Parameters)
  * **รายละเอียด:** ดัดแปลงมาจากโครงสร้าง `large-v3` โดยลดจำนวน Decoder Layers ลงจาก 32 เหลือเพียง 4 Layers
  * **คุณสมบัติ:** ให้ความเร็วใกล้เคียงกับรุ่น `small`/`medium` แต่รักษาความแม่นยำไว้ได้ใกล้เคียงกับ `large-v3` มาก

---

## 3. Distilled Models (รุ่นบีบอัดพิเศษ)

โมเดลที่ผ่านกระบวนการ Knowledge Distillation เพื่อถอดรหัส (Decode) ได้เร็วขึ้น 6-7 เท่า และใช้ VRAM น้อยลง

* `distil-small.en` *(ภาษาอังกฤษเท่านั้น)*
* `distil-medium.en` *(ภาษาอังกฤษเท่านั้น)*
* `distil-large-v2`
* `distil-large-v3`
* `distil-large-v3.5`

---

## 4. Code Snippets & Custom Model Usage

### การดึงรายชื่อ Built-in Models ใน Python
```python
from faster_whisper.utils import available_models

print(available_models())
```

### การโหลดโมเดลใช้งาน
```python
from faster_whisper import WhisperModel

# 1. โหลดด้วยชื่อ Built-in ID
model = WhisperModel("large-v3-turbo", device="cuda", compute_type="float16")

# 2. โหลดโมเดล Custom / Fine-tuned จาก Hugging Face Hub Directly
model = WhisperModel("Systran/faster-whisper-large-v3", device="cuda")
```

---

## 5. คำแนะนำสำหรับการใช้งานในโปรเจกต์ (ChooNova Transcribe)

1. **สำหรับภาษาไทย (`th`):**
   * **`large-v3` / `turbo`**: แนะนำเป็นหลักเมื่อต้องการความแม่นยำสูง
   * **`medium`**: เหมาะสำหรับเครื่องที่มี VRAM จำกัด (~3-4 GB)
2. **สำหรับภาษาอังกฤษ (`en`):**
   * สามารถใช้รุ่น `.en` หรือ `distil-*.en` เพื่อประมวลผลได้เร็วยิ่งขึ้น
