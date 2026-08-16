แบบนี้เราจะกำหนด language=th แต่ใช้ WhisperX ได้ใหม เราเปลี่ยนวิธีเลือกได้ใหม แต่ต้องเปลี่ยน api ให้สอดคล้องกันด้วย
โดยเปลี่ยน วิธีการคือ

1. กรณีไม่ติ๊ก ระบุผู้พูด (Speaker Diarization)

- เลือก language เป็น th จะมี model มาให้เลือกสองตัว คือ Thypoon ASR และ faster-whisper (large-v3-turbo)
- เลือก language เป็น en จะมี model มาให้เลือกตัวเดียวคือ faster-whisper (large-v3-turbo)
- เลือก language เป็น auto จะมี model มาให้เลือกตัวเดียวคือ faster-whisper (large-v3-turbo)

2. กรณีติ๊ก ระบุผู้พูด (Speaker Diarization)

- เลือก language เป็น th จะมี model มาให้เลือกสองตัว คือ Thai Whisper (คำต่อคำจริง + PyAnnote group_words_by_turns แบบปัจจุบัน) และ WhisperX
- เลือก language เป็น en จะมี model มาให้เลือกตัวเดียวคือ WhisperX
- เลือก language เป็น auto จะมี model มาให้เลือกตัวเดียวคือ WhisperX

คุณว่าแบบนี้ดีใหม เราจะได้ทดสอบได้ว่าอะไรแม่นสุดแล้วเลือกใช้ได้ จะแก้ก็ค่อยแก้เป็นอันๆ ไปเลย

---

คุณช่วยทดสอบการทำ word-level + การตรวจจับผู้พูด กับ api endpoint ของ /audio/transcribe/jobs กับไฟล์ test-audio-th.wav ว่าได้ผลลัพแบบที่ควรเป็นใหม มีข้อมูล words ด้วย โดยตรวจสอบที่โมเดล Thai whisper และ whisperx โดยทดสอบทีละ model

---

คุณช่วยทดสอบการทำ word-level + ไม่มีการตรวจจับผู้พูด กับ api endpoint ของ /audio/transcribe/jobs กับไฟล์ test-audio-th.wav ว่าได้ผลลัพแบบที่ควรเป็นใหม มีข้อมูล words ด้วย โดยตรวจสอบที่โมเดล Thai Whisper และ Faster Whisper (large-v3-turbo) โดยทดสอบทีละ model

---

คุณช่วยทดสอบ ไม่ทำ word-level + ไม่มีการตรวจจับผู้พูด กับ api endpoint ของ /audio/transcribe/jobs กับไฟล์ test-audio-th.wav ว่าได้ผลลัพแบบที่ควรเป็นใหม ไม่ควรมีข้อมูล words โดยตรวจสอบที่โมเดล Typhoon ASR, Thai Whisper และ Faster Whisper (large-v3-turbo) โดยทดสอบทีละ model

---
