# Gradio - Tech Report

> **Issue Reference**: [#21 - Voice Quality Issues for Podcast Output](https://github.com/maemreyo/omnivoice-server/issues/21)  
> **Research Date**: 2026-04-18  
> **Website**: [gradio.app](https://www.gradio.app/)  
> **GitHub**: [gradio-app/gradio](https://github.com/gradio-app/gradio)  
> **PyPI**: `gradio`  
> **Documentation**: [gradio.app/guides](https://www.gradio.app/guides)

---

## Overview

**Gradio** is an open-source Python library that enables creating interactive web interfaces for machine learning models with just a few lines of code. Developed by Hugging Face, Gradio is a popular tool for ML model demos and sharing.

---

## Key Characteristics

| Aspect | Details |
|--------|---------|
| **Language** | Python (frontend auto-generated) |
| **Architecture** | Python backend + JavaScript frontend |
| **License** | Apache 2.0 |
| **Maintainer** | Hugging Face |
| **GitHub Stars** | 42,000+ |
| **Deployment** | Local, HuggingFace Spaces, Docker |

---

## Core Features

| Feature | Description |
|---------|-------------|
| **40+ Components** | Text, Image, Audio, Video, Dataframe, Chatbot, etc. |
| **No Frontend Code** | Only Python needed, no HTML/CSS/JS |
| **One-line Deploy** | `demo.launch()` to run locally or publicly |
| **HuggingFace Integration** | Deploy to Spaces for free |
| **API Auto-generation** | Automatically generates REST API for every demo |
| **Streaming Support** | Real-time output for audio, text generation |

---

## Architecture

```
Gradio Application
├── Python Backend
│   ├── User-defined function(s)
│   ├── Input preprocessing
│   └── Output postprocessing
├── Gradio Server (FastAPI-based)
│   ├── HTTP routes
│   ├── WebSocket (for streaming)
│   └── Queue management
└── Auto-generated Frontend
    ├── React components
    ├── Real-time updates
    └── Mobile-responsive UI
```

---

## Components Relevant to TTS

### Audio Components

| Component | Purpose | Example Use Case |
|-----------|---------|------------------|
| `gr.Audio` | Audio input/output | Upload reference audio, play generated speech |
| `gr.File` | File upload/download | Batch audio processing |
| `gr.Textbox` | Text input | Enter text to synthesize |
| `gr.Dropdown` | Voice selection | Select voice preset |
| `gr.Slider` | Parameter control | Speed, pitch adjustment |
| `gr.Button` | Trigger actions | Generate, download |

### Code Example

```python
import gradio as gr

def tts_demo(text, voice_preset, speed):
    # Call OmniVoice-server API
    audio = generate_speech(text, voice_preset, speed)
    return audio

demo = gr.Interface(
    fn=tts_demo,
    inputs=[
        gr.Textbox(label="Text to synthesize"),
        gr.Dropdown(
            choices=["ash", "alloy", "nova", "onyx", "shimmer"],
            label="Voice"
        ),
        gr.Slider(minimum=0.25, maximum=4.0, value=1.0, label="Speed")
    ],
    outputs=gr.Audio(label="Generated Speech"),
    title="OmniVoice TTS Demo"
)

demo.launch()
```

---

## Gradio in Context of Issue #21

### Current Usage in Ecosystem

```
OmniVoice (k2-fsa/OmniVoice)
    └── Gradio Demo (omnivoice-demo CLI)
        └── Local Web UI for voice cloning/design

OmniVoice-server
    └── No Gradio UI (API-only)
    
Open Notebook
    └── Next.js Frontend (does not use Gradio)
    └── Podcastfy Backend (does not use Gradio)
```

### OmniVoice Gradio Demo

OmniVoice provides Gradio web UI via command:

```bash
omnivoice-demo --ip 0.0.0.0 --port 8001
```

Features:
- Voice Cloning interface
- Voice Design interface  
- Audio playback
- Parameter adjustment

---

## Gradio vs Open Notebook (for Issue #21 Context)

| Aspect | Gradio Demo | Open Notebook |
|--------|-------------|---------------|
| **Purpose** | Demo/Testing | Production Podcast Generation |
| **Interface** | Simple form-based | Full-featured notebook UI |
| **Multi-speaker** | Limited | Full support |
| **Content Sources** | Direct text input | PDFs, URLs, YouTube, etc. |
| **Podcast Assembly** | Manual | Automated (Podcastfy) |
| **Use Case** | Individual TTS | Long-form podcast production |

---

## Streaming Audio Support

Gradio supports streaming audio, suitable for real-time TTS:

```python
import gradio as gr

def stream_tts(text):
    # Generator function for streaming
    for audio_chunk in generate_audio_streaming(text):
        yield audio_chunk

demo = gr.Interface(
    fn=stream_tts,
    inputs=gr.Textbox(),
    outputs=gr.Audio(streaming=True),
    live=True
)
```

### Relevance to OmniVoice-server

OmniVoice-server currently supports sentence-level streaming. Gradio can consume this streaming endpoint.

---

## API Auto-generation

Gradio automatically generates REST API for every demo:

```python
# Gradio app running on port 7860
# Auto-generated API:
# POST /api/predict/ - Make prediction
# GET /api/info/ - Get component info
```

### Use Case: Testing OmniVoice-server

You can build a quick Gradio interface to test OmniVoice-server instead of Open Notebook:

```python
import gradio as gr
import requests

def test_omnivoice_server(text, voice):
    response = requests.post(
        "http://localhost:8880/v1/audio/speech",
        json={"model": "omnivoice", "input": text, "voice": voice}
    )
    return response.content

# Quick debugging tool for issue #21
```

---

## Deployment Options

| Method | Command | Use Case |
|--------|---------|----------|
| **Local** | `demo.launch()` | Development, testing |
| **Public Share** | `demo.launch(share=True)` | Temporary public URL |
| **HuggingFace Spaces** | Push to repo | Permanent free hosting |
| **Docker** | `docker run` | Self-hosted production |

---

## Gradio Limitations

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| **Single-session state** | No persistent data | Use database |
| **No built-in auth** | Open to all | Reverse proxy with auth |
| **Queue limit** | 1 concurrent by default | Configure queue |
| **Not for heavy load** | More suitable for demo than production | Use FastAPI directly |

---

## Connection to Issue #21

### Why Gradio is Mentioned

User mentioned testing with "official webui demo (early April version)" with the same inconsistent voice issue. This could be the OmniVoice Gradio demo or Open Notebook's UI.

### Debugging Suggestion

Create Gradio test harness to isolate the issue:

```python
import gradio as gr
import requests

def test_voice_consistency(text, voice, num_samples=3):
    """Generate multiple samples to test consistency"""
    audios = []
    for i in range(num_samples):
        response = requests.post(
            "http://localhost:8880/v1/audio/speech",
            json={"model": "omnivoice", "input": text, "voice": voice}
        )
        audios.append(response.content)
    return audios

# Gradio UI to reproduce issue #21
demo = gr.Interface(
    fn=test_voice_consistency,
    inputs=[
        gr.Textbox(value="Hello world"),
        gr.Dropdown(["ash", "alloy", "auto"]),
        gr.Slider(1, 5, value=3, step=1)
    ],
    outputs=[gr.Audio() for _ in range(5)],
    title="Voice Consistency Test"
)
```

---

## Integration Possibilities

### Option 1: Add Gradio UI to OmniVoice-server

```python
# In omnivoice-server, add optional Gradio interface
@app.on_event("startup")
async def setup_gradio():
    if settings.ENABLE_GRADIO:
        gradio_demo = create_gradio_interface()
        gradio_demo.launch(server_port=7860)
```

**Pros**: Easy testing, debugging
**Cons**: Additional dependency

### Option 2: Separate Gradio Debug Tool

Create standalone Gradio app in `tools/` directory for debugging.

---

## Related Technologies

- **Streamlit**: Alternative to Gradio for Python data apps
- **FastAPI**: Backend framework (Gradio uses FastAPI internally)
- **React**: Frontend framework (Gradio auto-generates React code)
- **HuggingFace Spaces**: Hosting platform for Gradio apps

---

## Conclusion

Gradio is not directly related to the root cause of issue #21, but:

1. **OmniVoice has Gradio demo** - User tested and found the same inconsistent voice issue
2. **Gradio can be a debugging tool** - Create test harness to reproduce and fix issues
3. **Gradio UI is nice-to-have** for OmniVoice-server in the future

To investigate issue #21, Gradio can be used as a tool to:
- Test API endpoints directly
- Reproduce consistency issues
- Validate fixes

---

*Report generated for issue #21 investigation*