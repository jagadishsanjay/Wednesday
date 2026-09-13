"""Voice-controlled Wednesday using sounddevice instead of PyAudio."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import traceback
import webbrowser
from datetime import datetime

try:
    import pyttsx3
    import speech_recognition as sr
    import sounddevice as sd
    import numpy as np
except ImportError as import_error:
    print(f"Missing dependency: {import_error}")
    print("Install everything this script needs with:")
    print("    pip install pyttsx3 SpeechRecognition sounddevice numpy")
    print("(On Linux you may also need: sudo apt-get install libportaudio2 espeak)")
    sys.exit(1)
except OSError as os_error:
    # sounddevice raises OSError (not ImportError) when the *system*
    # PortAudio library is missing -- `pip install sounddevice` alone
    # does not install it on Linux.
    print(f"System audio library error: {os_error}")
    print("This usually means PortAudio (and/or espeak for text-to-speech)")
    print("isn't installed at the OS level. On Debian/Ubuntu, run:")
    print("    sudo apt-get update && sudo apt-get install -y libportaudio2 espeak")
    print("Then re-run this script.")
    sys.exit(1)


class Wednesday:
    def __init__(self) -> None:
        try:
            self.engine = pyttsx3.init()
        except Exception as error:
            print(f"Warning: TTS engine failed to initialize: {error}")
            self.engine = None

        self.recognizer = sr.Recognizer()
        self.running = True

        # Was hardcoded to 16000, which many mics (especially built-in/USB
        # ones on Windows) don't actually support as a recording rate.
        # sd.rec() then raises a PortAudioError on every single call, which
        # was getting silently swallowed in listen()'s except block, making
        # the app look "unresponsive" instead of erroring loudly.
        # speech_recognition doesn't require 16kHz specifically -- any rate
        # works as long as we tell sr.AudioData the real rate -- so just use
        # whatever the device natively supports.
        self.sample_rate = 16000
        self._check_microphone()

    def _check_microphone(self) -> None:
        try:
            devices = sd.query_devices()
            print("\nAvailable audio devices:")
            for i, d in enumerate(devices):
                marker = " <-- default input" if i == sd.default.device[0] else ""
                print(f"  [{i}] {d['name']} "
                      f"(in:{d['max_input_channels']} "
                      f"rate:{int(d['default_samplerate'])}){marker}")

            default_input = sd.default.device[0]
            if default_input is None or default_input == -1:
                print("Warning: No default input (microphone) device found. "
                      "Set sd.default.device = <index from the list above>.")
                return

            device_info = devices[default_input]
            print(f"\nUsing input device: {device_info['name']}")

            # Use the device's own default sample rate instead of a
            # hardcoded value that may not be supported.
            native_rate = int(device_info['default_samplerate'])
            if native_rate:
                self.sample_rate = native_rate
                print(f"Recording at {self.sample_rate} Hz "
                      f"(device's native rate)")
        except Exception as error:
            print(f"Warning: Could not query audio devices: {error}")

    def respond(self, message: str) -> None:
        print(f"Wednesday: {message}")
        if self.engine is None:
            return
        try:
            self.engine.say(message)
            self.engine.runAndWait()
        except RuntimeError as error:
            print(f"Wednesday: Text-to-speech is unavailable: {error}")

    def listen(self, duration: float = 5.0) -> str:
        print("\nListening...")
        try:
            audio_data = sd.rec(int(duration * self.sample_rate),
                                 samplerate=self.sample_rate,
                                 channels=1,
                                 dtype='int16')
            sd.wait()

            peak = np.abs(audio_data).max()
            print(f"Audio peak level: {peak}")

            if peak < 50:
                print("Heard nothing (silence).")
                return ""

            audio_bytes = audio_data.tobytes()
            audio = sr.AudioData(audio_bytes, self.sample_rate, 2)
            command = self.recognizer.recognize_google(audio)
            print(f"You said: {command}")
            return command.lower().strip()
        except sr.UnknownValueError:
            self.respond("Sorry, I couldn't understand that.")
            return ""
        except sr.RequestError as error:
            self.respond(f"Speech recognition service error: {error}")
            return ""
        except Exception as error:
            # Print the full traceback so real problems (e.g. an
            # unsupported sample rate / PortAudio error) are visible
            # instead of getting lost as a one-line message.
            print("Microphone error - full traceback:")
            traceback.print_exc()
            self.respond(f"Microphone error: {error}")
            return ""

    WAKE_WORDS = ("wake up", "hey wednesday", "wednesday")

    def _wait_for_wake_word(self) -> None:
        print("\nSleeping... say 'wake up' to activate.")
        while self.running:
            heard = self.listen(duration=3.0)
            if not heard:
                continue
            if any(wake_word in heard for wake_word in self.WAKE_WORDS):
                self.respond("Yes? Go ahead.")
                return

    def process_command(self, command: str) -> None:
        if not command:
            return

        command = command.strip()
        for wake_word in ("hey wednesday", "wednesday", "wake up"):
            if command.startswith(wake_word):
                command = command[len(wake_word):].strip()
                break

        if not command:
            self.respond("Yes? Go ahead.")
            return

        if "time" in command:
            now = datetime.now().strftime("%I:%M %p")
            self.respond(f"The time is {now}")
        elif "date" in command:
            today = datetime.now().strftime("%B %d, %Y")
            self.respond(f"Today's date is {today}")
        elif any(word in command for word in ("exit", "quit", "stop", "bye")):
            self.respond("Goodbye!")
            self.running = False
        elif "play" in command and "spotify" in command:
            self._play_on_spotify(command)
        elif "play" in command:
            self._play_on_youtube(command)
        elif "search" in command and "youtube" in command:
            self._search_on_youtube(command)
        elif "spotify" in command:
            self._open_application("spotify")
        elif "open" in command:
            idx = command.find("open")
            target = command[idx + len("open"):].strip()
            if not target:
                self.respond("What should I open?")
                return
            self._open_application(target)
        else:
            self.respond(f"I heard '{command}' but I don't have a command for that yet.")

    # Windows-only URI form. On Linux/macOS we look up the plain binary
    # name instead (see _open_application) — using "spotify:" there would
    # make shutil.which()/`open -a` fail to find the real app.
    APP_ALIASES_WINDOWS = {
        "spotify": "spotify:",
        "chrome": "chrome",
        "notepad": "notepad",
        "calculator": "calc",
        "calc": "calc",
    }

    WEBSITE_ALIASES = {
        "youtube": "https://www.youtube.com",
        "google": "https://www.google.com",
        "gmail": "https://mail.google.com",
        "facebook": "https://www.facebook.com",
        "instagram": "https://www.instagram.com",
        "whatsapp": "https://web.whatsapp.com",
        "twitter": "https://www.twitter.com",
        "x": "https://www.x.com",
        "netflix": "https://www.netflix.com",
        "chatgpt": "https://chat.openai.com",
        "github": "https://github.com",
        "github account": "https://github.com/login"
    }

    def _open_application(self, name: str) -> None:
        name = name.strip().lower()

        if name in self.WEBSITE_ALIASES:
            try:
                webbrowser.open(self.WEBSITE_ALIASES[name])
                self.respond(f"Opening {name}")
            except Exception as error:
                self.respond(f"Couldn't open {name}: {error}")
            return

        system = platform.system()
        try:
            if system == "Windows":
                target = self.APP_ALIASES_WINDOWS.get(name, name)
                os.startfile(target)
            elif system == "Darwin":
                subprocess.Popen(["open", "-a", name])
            else:
                path = shutil.which(name)
                if path is None:
                    self.respond(f"Couldn't find an application called {name}.")
                    return
                subprocess.Popen([path])
            self.respond(f"Opening {name}")
        except FileNotFoundError:
            self.respond(f"Couldn't find an application called {name}.")
        except Exception as error:
            self.respond(f"Couldn't open {name}: {error}")

    def _play_on_spotify(self, command: str) -> None:
        text = command.lower()
        for phrase in ("on spotify", "in spotify", "using spotify"):
            text = text.replace(phrase, "")
        if text.strip().startswith("play"):
            text = text.strip()[len("play"):]
        for filler in ("song", "independently", "independent", "please"):
            text = text.replace(filler, "")
        song = text.strip()

        if not song:
            self.respond("What song do you want me to play?")
            return

        query = song.replace(" ", "%20")
        try:
            if platform.system() == "Windows":
                os.startfile(f"spotify:search:{query}")
            else:
                webbrowser.open(f"spotify:search:{query}")
            self.respond(f"Searching Spotify for {song}")
        except Exception:
            try:
                webbrowser.open(f"https://open.spotify.com/search/{query}")
                self.respond(f"Opening Spotify web search for {song}")
            except Exception as error:
                self.respond(f"Couldn't open Spotify: {error}")

    @staticmethod
    def _clean_query(command: str, trigger_word: str, platform_word: str) -> str:
        text = command.lower()
        for phrase in (f"on {platform_word}", f"in {platform_word}", f"using {platform_word}"):
            text = text.replace(phrase, "")
        text = text.replace(platform_word, "")
        if text.strip().startswith(trigger_word):
            text = text.strip()[len(trigger_word):]
        for filler in ("video", "song", "independently", "independent", "please"):
            text = text.replace(filler, "")
        return text.strip()

    def _play_on_youtube(self, command: str) -> None:
        query = self._clean_query(command, "play", "youtube")
        if not query:
            self.respond("What video do you want me to play?")
            return

        try:
            import pywhatkit
        except ImportError:
            self.respond("pywhatkit isn't installed. Run: pip install pywhatkit")
            return

        self.respond(f"Playing {query} on YouTube")
        try:
            pywhatkit.playonyt(query)
        except Exception as error:
            q = query.replace(" ", "+")
            webbrowser.open(f"https://www.youtube.com/results?search_query={q}")
            self.respond(f"Couldn't auto-play, opened search results instead: {error}")

    def _search_on_youtube(self, command: str) -> None:
        query = self._clean_query(command, "search", "youtube")
        if not query:
            self.respond("What do you want me to search on YouTube?")
            return
        q = query.replace(" ", "+")
        webbrowser.open(f"https://www.youtube.com/results?search_query={q}")
        self.respond(f"Searching YouTube for {query}")

    def run(self) -> None:
        self.respond("Wednesday is online. Say 'wake up' to activate me.")
        while self.running:
            self._wait_for_wake_word()
            if not self.running:
                break
            command = self.listen()
            self.process_command(command)


def main() -> None:
    print(f"[DEBUG] Running script: {os.path.abspath(__file__)}")
    print(f"[DEBUG] Using Python:   {sys.executable}")
    wednesday = Wednesday()
    try:
        wednesday.run()
    except KeyboardInterrupt:
        print("\nInterrupted. Shutting down.")
        sys.exit(0)


if __name__ == "__main__":
    main()