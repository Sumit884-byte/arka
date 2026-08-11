# Noise Remove

Remove background noise from audio or video files locally with ffmpeg's `afftdn` filter.

## Requirements

- **ffmpeg** and **ffprobe** on `PATH` (`brew install ffmpeg` or `sudo apt install ffmpeg`)
- No extra Python packages — uses ffmpeg only

## CLI

```bash
arka noise_remove interview.wav
arka noise_remove clip.mp4 --strength 18
arka noise_remove webinar.mp4 --audio-only -o clean.wav
arka noise_remove check
```

## Natural language

- "remove noise from recording.wav"
- "denoise interview.mp4"
- "clean background noise from podcast.mp3"

## Behavior

- **Audio inputs**: denoise in place to `<name>-denoised.<ext>` (or `-o` path)
- **Video inputs**: copy the video stream and replace audio with a denoised track (default)
- **`--audio-only`**: extract and denoise audio from video without re-muxing

## Limitations

- Uses generic FFT denoising (`afftdn`), not AI speech enhancement
- Very noisy or music-heavy sources may sound dull at high strength — tune `--strength` (default 12 dB)
