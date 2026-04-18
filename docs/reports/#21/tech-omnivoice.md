# OmniVoice (k2-fsa/OmniVoice) - Tech Report

> **Issue Reference**: [#21 - Voice Quality Issues for Podcast Output](https://github.com/maemreyo/omnivoice-server/issues/21)
> **Research Date**: 2026-04-18
> **GitHub**: [k2-fsa/OmniVoice](https://github.com/k2-fsa/OmniVoice)
> **PyPI**: `omnivoice`
> **HuggingFace**: [k2-fsa/OmniVoice](https://huggingface.co/k2-fsa/OmniVoice)
> **Paper**: [arXiv:2604.00688](https://arxiv.org/abs/2604.00688)

---

## Overview

**OmniVoice** is a state-of-the-art zero-shot multilingual text-to-speech (TTS) model supporting over 600 languages. The model is built on a diffusion language model-style architecture, producing high-quality speech with superior inference speed.

---

## Key Specifications

| Specification | Value |
|--------------|-------|
| **Architecture** | Diffusion Language Model-style |
| **Languages** | 600+ languages (broadest among zero-shot TTS) |
| **Sample Rate** | 24 kHz |
| **RTF (Real-Time Factor)** | 0.025 - 0.2 (40x faster than real-time on GPU) |
| **Voice Cloning** | Zero-shot, 3-10 seconds reference |
| **Voice Design** | Gender, age, pitch, accent, dialect |
| **License** | Open source (k2-fsa) |

---

## Architecture Deep Dive

### Model Components

```
OmniVoice Model
├── Text Encoder
│   └── Tokenizes input + phoneme conversion
├── Voice Encoder (for cloning)
│   └── Extracts speaker embeddings from reference audio
├── Diffusion Language Model
│   ├── Iterative denoising process
│   ├── num_step: 16 (fast) / 32 (quality)
│   └── guidance_scale: controls output quality
└── Vocoder
    └── Converts mel-spectrogram to waveform (24kHz)
```

### Generation Modes

```
1. Voice Cloning Mode
   Input: text + ref_audio + ref_text
   └── Replicates voice from reference

2. Voice Design Mode
   Input: text + instruct (attributes)
   └── Generates voice based on description

3. Auto Voice Mode
   Input: text only
   └── Random voice selection
```

---

## Voice Design Attributes

### English Accents (10)

| Accent | Description |
|--------|-------------|
| `american` | US English |
| `british` | UK English |
| `australian` | Australian |
| `canadian` | Canadian |
| `indian` | Indian English |
| `chinese` | Chinese-accented English |
| `korean` | Korean-accented English |
| `japanese` | Japanese-accented English |
| `portuguese` | Portuguese-accented English |
| `russian` | Russian-accented English |

### Chinese Dialects (12)

| Dialect | Region |
|---------|--------|
| 河南话 | Henan |
| 陕西话 | Shaanxi |
| 四川话 | Sichuan |
| 贵州话 | Guizhou |
| 云南话 | Yunnan |
| 桂林话 | Guilin |
| 济南话 | Jinan |
| 石家庄话 | Shijiazhuang |
| 甘肃话 | Gansu |
| 宁夏话 | Ningxia |
| 青岛话 | Qingdao |
| 东北话 | Northeast |

### Other Attributes

| Category | Values |
|----------|--------|
| **Gender** | male, female |
| **Age** | child, teenager, young adult, adult, middle-aged, elderly |
| **Pitch** | very low, low, moderate, high, very high |
| **Style** | whisper |

---

## Generation Parameters

| Parameter | Default | Range | Description |
|-----------|---------|-------|-------------|
| `num_step` | 32 | 16-50 | Diffusion steps (higher = better quality, slower) |
| `speed` | 1.0 | 0.25-4.0 | Speaking speed multiplier |
| `guidance_scale` | 2.0 | 1.0-5.0 | Classifier-free guidance scale |
| `t_shift` | 0.1 | - | Time shift for generation |
| `position_temperature` | 5.0 | - | Position encoding temperature |
| `class_temperature` | 0.0 | - | Classifier temperature |
| `layer_penalty_factor` | 5.0 | - | Layer penalty factor |
| `duration` | None | - | Fixed output duration (overrides speed) |
| `denoise` | True | bool | Apply denoising |
| `preprocess_prompt` | True | bool | Preprocess reference prompt |
| `postprocess_output` | True | bool | Postprocess output audio |

---

## Non-verbal Symbols

OmniVoice supports 13 non-verbal tags:

| Tag | Description |
|-----|-------------|
| `[laughter]` | Laughter sound |
| `[sigh]` | Sighing sound |
| `[confirmation-en]` | English confirmation (uh-huh) |
| `[question-en]` | English question sound |
| `[question-ah]` | Ah-question sound |
| `[question-oh]` | Oh-question sound |
| `[question-ei]` | Ei-question sound |
| `[question-yi]` | Yi-question sound |
| `[surprise-ah]` | Surprised ah |
| `[surprise-oh]` | Surprised oh |
| `[surprise-wa]` | Surprised wa |
| `[surprise-yo]` | Surprised yo |
| `[dissatisfaction-hnn]` | Dissatisfaction sound |

---

## Pronunciation Control

### Chinese Pinyin

```python
text = "这批货物打ZHE2出售后他严重SHE2本了，再也经不起ZHE1腾了。"
# ZHE2 = 折 (discount)
# SHE2 = 折 (loss)
# ZHE1 = 折 (fold/torture)
```

### English CMU Phonemes

```python
text = "He plays the [B EY1 S] guitar while catching a [B AE1 S] fish."
# [B EY1 S] = bass (guitar)
# [B AE1 S] = bass (fish)
```

---

## Known Issues & Limitations

### From Issue #21 Analysis

| Issue | Description | Likely Cause |
|-------|-------------|--------------|
| **Random Seed Variation** | Each generation of the same text produces a different voice | Model uses random sampling in diffusion process |
| **Weird Noise Artifacts** | Voice has noise at 5m19s in the example | Could be: 1) Model limitation, 2) Text preprocessing issue, 3) Numerical instability |
| **Cross-lingual Accent** | Cloned voice across different languages retains accent | Expected behavior per documentation |

### Documented Limitations

1. **MPS (Apple Silicon)**: Known issues with PyTorch MPS backend
2. **Voice Design**: Trained on Chinese/English only, unstable for low-resource languages
3. **Reference Audio**: 3-10 seconds optimal, longer degrades quality
4. **Arabic Numerals**: Should normalize to words first
5. **Long-form Generation**: May have consistency issues across chunks

---

## Performance Benchmarks

| Device | RTF | Real-time Speed |
|--------|-----|-----------------|
| CPU | ~4.92 | 5x slower than real-time |
| CUDA (GPU) | ~0.2 | 5x faster than real-time |
| MPS (Apple Silicon) | Broken | Use CPU fallback |

---

## Integration via OmniVoice-server

OmniVoice-server provides an OpenAI-compatible HTTP API wrapper for OmniVoice:

```
Open Notebook / Podcastfy
    ↓ HTTP API
omnivoice-server
    ↓ Python API
OmniVoice (k2-fsa/OmniVoice)
    ↓ PyTorch
Model Weights (HuggingFace)
```

### API Mapping

| OmniVoice Function | OmniVoice-server Endpoint |
|-------------------|---------------------------|
| `model.generate(text, ref_audio, ref_text)` | `POST /v1/audio/speech` with clone params |
| `model.generate(text, instruct)` | `POST /v1/audio/speech` with design params |
| Voice profiles | `GET/POST /v1/voices/profiles` |
| Batch inference | Not yet implemented in server |

---

## Root Cause Analysis for Issue #21

### Issue 1: Inconsistent Voice Per Transcript

**Root Cause**: OmniVoice uses random sampling in the diffusion process. Each generation is independent.

**Evidence**:
```python
# OmniVoice generates with random seed each time
audio = model.generate(text="Hello")  # Random voice
audio = model.generate(text="Hello")  # Different random voice
```

**Solution Options**:
1. **Fixed Seed**: OmniVoice-server can add a seed parameter
2. **Voice Profiles**: Use clone voice instead of auto voice
3. **Design Mode**: Use specific attributes instead of auto

### Issue 2: Weird Noise at 5m19s

**Possible Causes**:
1. **Text Normalization**: Numbers or special characters not normalized
2. **Model Bug**: Numerical instability with certain phoneme sequences
3. **Chunking Issue**: Long-form generation may have boundary artifacts

**Debugging**:
```bash
# Test with text at 5m19s position
# Check for special characters
# Try normalizing numbers to words
```

### Issue 3: Clone Voice Not Working

**Hypothesis**: Not an OmniVoice bug, but an integration issue between Open Notebook and OmniVoice-server.

**Verification**:
```bash
# Test direct API
curl -X POST http://localhost:8880/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "model": "omnivoice",
    "input": "Test voice cloning",
    "voice": "clone:profile_id"
  }'
```

---

## Recommendations for Issue #21

### Immediate Actions

1. **Add Seed Parameter** (if not exists)
   - Allows reproducible generation
   - Solves inconsistent voice issue

2. **Improve Text Normalization**
   - Auto-convert numbers to words
   - Handle special characters

3. **Add Voice Consistency Mode**
   - Cache speaker embeddings
   - Re-use embeddings for the same voice

### Long-term

1. **Batch Inference API** to ensure consistency across segments
2. **Word-level streaming** for better chunking
3. **Enhanced clone voice persistence**

---

## Related Technologies

- **OmniVoice-server**: HTTP wrapper (this project)
- **OmniVoice-rs**: Rust implementation
- **Gradio**: Web UI demo for OmniVoice
- **k2-fsa**: Developing organization (Next-gen Kaldi)

---

## Conclusion

OmniVoice is a powerful TTS model with many advanced features. The issues in issue #21 may not be bugs in OmniVoice core, but rather:

1. **Expected behavior**: Random variation in auto mode
2. **Integration issue**: Clone voice not working via Open Notebook
3. **Potential bug**: Weird noise needs further investigation

To fully resolve issue #21, need to:
- Test OmniVoice-server API directly
- Verify Open Notebook integration
- Consider adding reproducibility features (seed control)

---

*Report generated for issue #21 investigation*