"""Behind `bb tool sound` (R107): sound effects a session makes for an app, and
the pictures that let it check one it cannot hear.

    bb tool sound make PRESET [--seed N] [--name NAME] [--wav]
        a sound effect from one of sfxr's presets (blip, pickup, jump, laser,
        hit, powerup, explosion, bloop), a fresh variation for each seed,
        into dist/sound/ as OGG (WAV with --wav or without ffmpeg)
    bb tool sound tone HZ [--ms N] [--to HZ] [--wave sine|square|saw|noise] [--name NAME]
        a plain tone or sweep with a quick fade, for a beep or a chime
    bb tool sound look FILE
        a waveform and a spectrogram of any sound file, as PNGs beside it
    bb tool sound presets
        the presets, in a line each
    bb tool sound say "TEXT" [--name NAME] [--ogg]
        speech, from piper, as a WAV to feed an app's microphone
    bb tool sound hear FILE
        what is said in a recording, as text with its times, from whisper

sfxr is Tomas Pettersson's generator for game sounds (public domain); this is
a port of its synthesizer, stdlib only: the parameters a preset picks, the
envelope, the slide, the vibrato, the arpeggio, the duty cycle, the phaser
and the two filters, rendered at 44.1 kHz with sfxr's 8x supersampling. The
OGG and the pictures are ffmpeg's, from the ffmpeg toolchain or PATH.

A session cannot listen to what it made. Each file comes with its waveform
and its spectrogram beside it, which a session reads with its image reader:
the length, the attack and decay, the pitch going up or down. Whether it
sounds right is the person's to say.

say and hear are the audio toolchain's (piper, and faster-whisper with the
base.en model), run with that toolchain's own Python; hear takes anything
ffmpeg reads, brought to the 16 kHz mono whisper wants.
"""
import math
import os
import random
import re
import shutil
import struct
import subprocess
import sys
import wave

RATE = 44100
PRESETS = {
    "blip": "a short select or menu blip",
    "pickup": "a coin or pickup: a bright rising pair of notes",
    "jump": "a jump: a square tone sliding up",
    "laser": "a laser or shoot: a fast falling zap",
    "hit": "a hit or hurt: a short noisy thud",
    "powerup": "a power-up: a rising, wobbling tone",
    "explosion": "an explosion: a long rumbling noise",
    "bloop": "a soft UI bloop: a rounded tone falling away",
}


def fail(msg):
    sys.exit(f"[builderbot] ERROR: {msg}")


class Params:
    """sfxr's parameters, all 0..1 (or -1..1 for the signed ones)."""
    def __init__(self):
        self.wave = 0                 # 0 square, 1 saw, 2 sine, 3 noise
        self.attack, self.sustain, self.punch, self.decay = 0.0, 0.3, 0.0, 0.4
        self.base, self.limit, self.ramp, self.dramp = 0.3, 0.0, 0.0, 0.0
        self.vib_strength, self.vib_speed = 0.0, 0.0
        self.arp_mod, self.arp_speed = 0.0, 0.0
        self.duty, self.duty_ramp = 0.0, 0.0
        self.repeat = 0.0
        self.pha_offset, self.pha_ramp = 0.0, 0.0
        self.lpf, self.lpf_ramp, self.lpf_res = 1.0, 0.0, 0.0
        self.hpf, self.hpf_ramp = 0.0, 0.0
        self.volume = 0.5


def preset(name, rnd):
    """sfxr's preset generators, each a family of sounds a seed picks from."""
    p = Params()
    r = rnd.random
    if name == "pickup":
        p.base = 0.4 + r() * 0.5
        p.sustain, p.decay, p.punch = r() * 0.1, 0.1 + r() * 0.4, 0.3 + r() * 0.3
        if r() < 0.5:
            p.arp_speed, p.arp_mod = 0.5 + r() * 0.2, 0.2 + r() * 0.4
    elif name == "laser":
        p.wave = rnd.choice([0, 1, 2])
        p.base = 0.5 + r() * 0.5
        p.limit = max(0.2, p.base - 0.2 - r() * 0.6)
        p.ramp = -0.15 - r() * 0.2
        if p.wave == 0:
            p.duty, p.duty_ramp = r() * 0.5, r() * 0.2
        p.sustain, p.decay, p.punch = 0.1 + r() * 0.2, r() * 0.4, r() * 0.3
        if r() < 0.3:
            p.pha_offset, p.pha_ramp = r() * 0.2, -r() * 0.2
        if r() < 0.5:
            p.hpf = r() * 0.3
    elif name == "explosion":
        p.wave = 3
        p.base = 0.1 + r() * 0.4 if r() < 0.5 else 0.2 + r() * 0.5
        p.ramp = -0.1 + r() * 0.4 if p.base < 0.4 else -0.2 - r() * 0.2
        p.base *= p.base
        if r() < 0.2:
            p.ramp = 0.0
        if r() < 0.33:
            p.repeat = 0.3 + r() * 0.5
        p.sustain, p.decay, p.punch = 0.1 + r() * 0.3, r() * 0.5, 0.2 + r() * 0.6
        if r() < 0.5:
            p.pha_offset, p.pha_ramp = -0.3 + r() * 0.9, -r() * 0.3
        if r() < 0.33:
            p.arp_speed, p.arp_mod = 0.6 + r() * 0.3, 0.8 - r() * 1.6
    elif name == "powerup":
        if r() < 0.5:
            p.wave = 1
        else:
            p.duty = r() * 0.6
        if r() < 0.5:
            p.base, p.ramp, p.repeat = 0.2 + r() * 0.3, 0.1 + r() * 0.4, 0.4 + r() * 0.4
        else:
            p.base, p.ramp = 0.2 + r() * 0.3, 0.05 + r() * 0.2
            if r() < 0.5:
                p.vib_strength, p.vib_speed = r() * 0.7, r() * 0.6
        p.sustain, p.decay = r() * 0.4, 0.1 + r() * 0.4
    elif name == "hit":
        p.wave = rnd.choice([0, 1, 3])
        if p.wave == 0:
            p.duty = r() * 0.6
        p.base, p.ramp = 0.2 + r() * 0.6, -0.3 - r() * 0.4
        p.sustain, p.decay = r() * 0.1, 0.1 + r() * 0.2
        if r() < 0.5:
            p.hpf = r() * 0.3
    elif name == "jump":
        p.wave, p.duty = 0, r() * 0.6
        p.base, p.ramp = 0.3 + r() * 0.3, 0.1 + r() * 0.2
        p.sustain, p.decay = 0.1 + r() * 0.3, 0.1 + r() * 0.2
        if r() < 0.5:
            p.hpf = r() * 0.3
        if r() < 0.5:
            p.lpf = 1.0 - r() * 0.6
    elif name == "blip":
        p.wave = rnd.choice([0, 1])
        if p.wave == 0:
            p.duty = r() * 0.6
        p.base = 0.2 + r() * 0.4
        p.sustain, p.decay, p.hpf = 0.1 + r() * 0.1, r() * 0.2, 0.1
    elif name == "bloop":
        # Not one of sfxr's own: the soft rounded tone a UI uses, a sine
        # falling a little and fading fast, low-passed so it has no edge.
        p.wave = 2
        p.base, p.ramp = 0.35 + r() * 0.15, -0.12 - r() * 0.1
        p.attack, p.sustain, p.decay = 0.0, 0.05 + r() * 0.05, 0.15 + r() * 0.1
        p.lpf, p.lpf_ramp = 0.5 + r() * 0.2, -0.05
    else:
        fail(f"no preset called {name}: bb tool sound presets lists them")
    return p


def synth(p, seed=0):
    """sfxr's synthesizer: a list of floats in -1..1 at RATE."""
    rnd = random.Random(seed)
    out = []
    period = 100.0 / (p.base * p.base + 0.001)
    max_period = 100.0 / (p.limit * p.limit + 0.001)
    slide = 1.0 - p.ramp ** 3 * 0.01
    dslide = -(p.dramp ** 3) * 0.000001
    square_duty = 0.5 - p.duty * 0.5
    square_slide = -p.duty_ramp * 0.00005
    arp_mod = (1.0 - p.arp_mod ** 2 * 0.9) if p.arp_mod >= 0 else (1.0 + p.arp_mod ** 2 * 10.0)
    arp_time, arp_limit = 0, int((1.0 - p.arp_speed) ** 2 * 20000 + 32)
    if p.arp_speed == 1.0:
        arp_limit = 0
    env_len = [int(p.attack ** 2 * 100000), int(p.sustain ** 2 * 100000), int(p.decay ** 2 * 100000)]
    env_stage, env_time = 0, 0
    fltp = fltdp = fltphp = 0.0
    fltw = p.lpf ** 3 * 0.1
    fltw_d = 1.0 + p.lpf_ramp * 0.0001
    fltdmp = min(0.8, 5.0 / (1.0 + p.lpf_res ** 2 * 20.0) * (0.01 + fltw))
    flthp = p.hpf ** 2 * 0.1
    flthp_d = 1.0 + p.hpf_ramp * 0.0003
    vib_phase, vib_speed, vib_amp = 0.0, p.vib_speed ** 2 * 0.01, p.vib_strength * 0.5
    phaser = [0.0] * 1024
    fphase = p.pha_offset ** 2 * 1020.0 * (1 if p.pha_offset >= 0 else -1)
    fdphase = p.pha_ramp ** 2 * (1 if p.pha_ramp >= 0 else -1)
    ipp = 0
    noise = [rnd.uniform(-1, 1) for _ in range(32)]
    phase = 0
    rep_time, rep_limit = 0, int((1.0 - p.repeat) ** 2 * 20000 + 32)
    if p.repeat == 0.0:
        rep_limit = 0
    base_period, base_slide = period, slide
    total = sum(env_len) or 1
    while len(out) < RATE * 4:
        rep_time += 1
        if rep_limit and rep_time >= rep_limit:
            rep_time = 0
            period, slide = base_period, base_slide
            arp_time = 0
        arp_time += 1
        if arp_limit and arp_time >= arp_limit:
            arp_limit = 0
            period *= arp_mod
        slide += dslide
        period *= slide
        if period > max_period:
            period = max_period
            if p.limit > 0:
                break
        rfperiod = period
        if vib_amp > 0:
            vib_phase += vib_speed
            rfperiod = period * (1.0 + math.sin(vib_phase) * vib_amp)
        iperiod = max(8, int(rfperiod))
        square_duty = min(0.5, max(0.0, square_duty + square_slide))
        env_time += 1
        if env_time > env_len[env_stage]:
            env_time = 0
            env_stage += 1
            if env_stage == 3:
                break
        if env_stage == 0:
            env_vol = env_time / env_len[0] if env_len[0] else 1.0
        elif env_stage == 1:
            env_vol = 1.0 + (1.0 - env_time / (env_len[1] or 1)) * 2.0 * p.punch
        else:
            env_vol = 1.0 - env_time / (env_len[2] or 1)
        fphase += fdphase
        iphase = min(1023, int(abs(fphase)))
        if flthp_d != 1.0:
            flthp = min(0.1, max(0.00001, flthp * flthp_d))
        ssample = 0.0
        for _ in range(8):
            phase += 1
            if phase >= iperiod:
                phase %= iperiod
                if p.wave == 3:
                    noise = [rnd.uniform(-1, 1) for _ in range(32)]
            fp = phase / iperiod
            if p.wave == 0:
                sample = 0.5 if fp < square_duty else -0.5
            elif p.wave == 1:
                sample = 1.0 - fp * 2
            elif p.wave == 2:
                sample = math.sin(fp * 2 * math.pi)
            else:
                sample = noise[int(phase * 32 / iperiod) % 32]
            pp = fltp
            fltw = min(0.1, max(0.0, fltw * fltw_d))
            if p.lpf != 1.0:
                fltdp += (sample - fltp) * fltw
                fltdp -= fltdp * fltdmp
            else:
                fltp, fltdp = sample, 0.0
            fltp += fltdp
            fltphp += fltp - pp
            fltphp -= fltphp * flthp
            sample = fltphp
            phaser[ipp & 1023] = sample
            sample += phaser[(ipp - iphase + 1024) & 1023]
            ipp = (ipp + 1) & 1023
            ssample += sample * env_vol
        out.append(ssample / 8)
    del total
    # Brought to one loudness, a peak of 0.8, rather than sfxr's fixed gain,
    # which clips a square with the phaser on and loses the envelope to it.
    peak = max((abs(x) for x in out), default=0.0) or 1.0
    return [x * 0.8 / peak for x in out]


def tone(hz, ms, to=None, wave_kind="sine"):
    """A tone, or a sweep from hz to `to`, with a 5 ms attack and an
    exponential fade, the shape of a UI beep or chime."""
    n = max(1, int(RATE * ms / 1000))
    out, ph = [], 0.0
    rnd = random.Random(1)
    for i in range(n):
        t = i / RATE
        f = hz + ((to - hz) * i / n if to else 0)
        ph += 2 * math.pi * f / RATE
        if wave_kind == "square":
            s = 1.0 if math.sin(ph) >= 0 else -1.0
        elif wave_kind == "saw":
            s = 2 * ((ph / (2 * math.pi)) % 1) - 1
        elif wave_kind == "noise":
            s = rnd.uniform(-1, 1)
        else:
            s = math.sin(ph)
        env = min(1.0, t / 0.005) * math.exp(-t * 6.0 / (ms / 1000))
        out.append(s * env * 0.6)
    return out


def write_wav(path, samples):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, s)) * 32767)) for s in samples))


def ffmpeg():
    """The store's ffmpeg, else PATH's, else "" (WAV only, no pictures)."""
    root = os.environ.get("SDK_ROOT", "")
    for c in ([os.path.join(root, "ffmpeg", "bin", "ffmpeg")] if root else []) + [shutil.which("ffmpeg") or ""]:
        if c and os.access(c, os.X_OK):
            return c
    return ""


def look(path):
    """A waveform and a spectrogram beside `path`, for a session to read."""
    ff = ffmpeg()
    if not ff:
        return []
    stem = os.path.splitext(path)[0]
    made = []
    for suffix, filt in (("wave", "showwavespic=s=900x220:colors=#4fb3ff:split_channels=0"),
                         ("spectrum", "showspectrumpic=s=900x300:legend=1:scale=log")):
        out = f"{stem}-{suffix}.png"
        r = subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y", "-i", path,
                            "-lavfi", filt, "-frames:v", "1", out], capture_output=True, text=True)
        if r.returncode == 0 and os.path.isfile(out):
            made.append(out)
    return made


def save(samples, name, as_wav):
    os.makedirs("dist/sound", exist_ok=True)
    wav = f"dist/sound/{name}.wav"
    write_wav(wav, samples)
    ff = ffmpeg()
    final = wav
    if not as_wav and ff:
        ogg = f"dist/sound/{name}.ogg"
        r = subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y", "-i", wav,
                            "-c:a", "libvorbis", "-q:a", "5", ogg], capture_output=True, text=True)
        if r.returncode == 0:
            final = ogg
    pics = look(final)
    if final != wav:
        os.remove(wav)
    ms = int(len(samples) * 1000 / RATE)
    print(f"{final}  ({ms} ms)")
    for p in pics:
        print(f"  {p}")
    if not ff:
        print("  (no ffmpeg on this node: WAV only and no pictures; the Toolchains page installs ffmpeg)")


def audio_tc():
    """The audio toolchain's directory, or a refusal that says how to get it."""
    root = os.environ.get("SDK_ROOT", "")
    d = os.path.join(root, "audio") if root else ""
    if not (d and os.access(os.path.join(d, "bin", "python-audio"), os.X_OK)):
        fail("say and hear need the audio toolchain on this node (piper and whisper); "
             "installing it is the operator's, from the Toolchains page")
    return d


# What hear runs inside the toolchain's Python: 16 kHz mono floats on stdin,
# one line per segment out. Half a second of silence goes first: speech that
# starts on the first sample lost its first word without it ("Set a timer"
# heard as "at a timer", 3 Oct), and the times are given back without it.
HEAR = """
import sys, numpy
from faster_whisper import WhisperModel
audio = numpy.frombuffer(sys.stdin.buffer.read(), dtype=numpy.float32)
audio = numpy.concatenate([numpy.zeros(8000, numpy.float32), audio])
m = WhisperModel(sys.argv[1], device="cpu", compute_type="int8")
segs, _ = m.transcribe(audio, language="en")
for s in segs:
    print(f"{max(0, s.start - 0.5):6.2f} to {max(0, s.end - 0.5):6.2f}  {s.text.strip()}")
"""


def voice(d):
    """The voice piper speaks with: ljspeech, trained on the public-domain LJ
    Speech dataset, which the audio toolchain installs; on a node installed
    before it, whichever voice is there, until it is installed again."""
    vd = os.path.join(d, "models", "voices")
    want = os.path.join(vd, "en_US-ljspeech-medium.onnx")
    if os.path.isfile(want):
        return want
    have = sorted(f for f in os.listdir(vd) if f.endswith(".onnx")) if os.path.isdir(vd) else []
    return os.path.join(vd, have[0]) if have else want


def say(text, name, as_ogg):
    d = audio_tc()
    if not text.strip():
        fail('bb tool sound say "TEXT": something to say')
    os.makedirs("dist/sound", exist_ok=True)
    stem = name or "say-" + (re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "speech")
    wav = f"dist/sound/{stem}.wav"
    r = subprocess.run([os.path.join(d, "bin", "piper"), "-m", voice(d), "-f", wav],
                       input=text, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.isfile(wav):
        fail("piper could not say it: " + (r.stderr.strip().splitlines() or ["no reason given"])[-1])
    final = wav
    ff = ffmpeg()
    if as_ogg and ff:
        ogg = f"dist/sound/{stem}.ogg"
        if subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y", "-i", wav, "-c:a", "libvorbis",
                           "-q:a", "5", ogg]).returncode == 0:
            os.remove(wav)
            final = ogg
    with_ms = ""
    if final == wav:
        with wave.open(wav) as w:
            with_ms = f"  ({int(w.getnframes() * 1000 / w.getframerate())} ms)"
    print(f"{final}{with_ms}")
    for p in look(final):
        print(f"  {p}")


def hear(path):
    d = audio_tc()
    ff = ffmpeg()
    if not ff:
        fail("hear needs ffmpeg to read the recording: the Toolchains page installs it")
    pcm = subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-i", path, "-ac", "1", "-ar", "16000",
                          "-f", "f32le", "-"], capture_output=True)
    if pcm.returncode != 0:
        fail("ffmpeg could not read it: " + pcm.stderr.decode(errors="replace").strip()[-300:])
    if not pcm.stdout:
        fail("there is no sound in it")
    r = subprocess.run([os.path.join(d, "bin", "python-audio"), "-c", HEAR,
                        os.path.join(d, "models", "whisper", "base.en")],
                       input=pcm.stdout, capture_output=True)
    if r.returncode != 0:
        fail("whisper could not hear it: " + r.stderr.decode(errors="replace").strip()[-300:])
    out = r.stdout.decode().strip()
    print(out or "(nothing said that whisper could make out)")


def opt(args, name, default=None):
    if name in args:
        i = args.index(name)
        if i + 1 >= len(args):
            fail(f"{name} takes a value")
        v = args[i + 1]
        del args[i:i + 2]
        return v
    return default


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.split("\n\n")[1])
        return
    verb, args = argv[0], argv[1:]
    as_wav, as_ogg = "--wav" in args, "--ogg" in args
    args = [a for a in args if a not in ("--wav", "--ogg")]
    name = opt(args, "--name")
    if name and not re.fullmatch(r"[A-Za-z0-9._-]{1,60}", name):
        fail("--name is letters, digits, dots, dashes and underscores")
    if verb == "presets":
        for k, v in PRESETS.items():
            print(f"  {k:<10} {v}")
    elif verb == "make":
        if not args:
            fail("bb tool sound make PRESET [--seed N]: bb tool sound presets lists them")
        kind = args[0].lower()
        seed = opt(args, "--seed", "0")
        if not seed.isdigit():
            fail("--seed is a whole number")
        seed = int(seed) or random.SystemRandom().randrange(1, 10**6)
        samples = synth(preset(kind, random.Random(seed)), seed)
        save(samples, name or f"{kind}-{seed}", as_wav)
        print(f"  seed {seed}: the same seed makes the same sound; another makes a variation")
    elif verb == "tone":
        if not args:
            fail("bb tool sound tone HZ [--ms N] [--to HZ] [--wave sine|square|saw|noise]")
        hz = ms = to = None
        try:
            hz = float(args[0])
            ms = int(opt(args, "--ms", "150"))
            to = opt(args, "--to")
            to = float(to) if to else None
        except ValueError:
            fail("tone takes numbers: HZ, --ms N, --to HZ")
        kind = opt(args, "--wave", "sine")
        if kind not in ("sine", "square", "saw", "noise") or not (20 <= hz <= 20000) or not (5 <= ms <= 10000):
            fail("a tone is 20 to 20000 Hz, 5 to 10000 ms, and a sine, square, saw or noise")
        save(tone(hz, ms, to, kind), name or f"tone-{int(hz)}{f'-{int(to)}' if to else ''}-{ms}ms", as_wav)
    elif verb == "say":
        say(" ".join(args), name, as_ogg)
    elif verb == "hear":
        if not args or not os.path.isfile(args[0]):
            fail("bb tool sound hear FILE: a recording that is there")
        hear(args[0])
    elif verb == "look":
        if not args or not os.path.isfile(args[0]):
            fail("bb tool sound look FILE: a sound file that is there")
        made = look(args[0])
        if not made:
            fail("no ffmpeg here to draw it: the Toolchains page installs ffmpeg")
        print("\n".join(made))
    else:
        fail(f"no verb {verb}: make, tone, say, hear, look or presets")


if __name__ == "__main__":
    main(sys.argv[1:])
