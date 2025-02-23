from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
import speech_recognition as sr
from gtts import gTTS
from googletrans import Translator, LANGUAGES
import tempfile
import subprocess
import os
import io
import base64
import time
from requests.exceptions import RequestException

# Initialize Flask app with correct static folder and template settings
app = Flask(__name__, static_folder='static', template_folder='.')
CORS(app)

MAX_RETRIES = 3
RETRY_DELAY = 1  # seconds

def create_translator():
    """Create a new translator instance with specific parameters."""
    return Translator(service_urls=[
        'translate.google.com',
        'translate.google.co.kr',
    ])

def detect_language_with_retry(text, max_retries=MAX_RETRIES):
    """Detect language with retry mechanism."""
    for attempt in range(max_retries):
        try:
            translator = create_translator()
            detection = translator.detect(text)
            return detection.lang
        except Exception as e:
            if attempt == max_retries - 1:
                print(f"Final language detection error: {e}")
                return None
            print(f"Language detection attempt {attempt + 1} failed: {e}")
            time.sleep(RETRY_DELAY)

def translate_text_with_retry(text, source_lang=None, target_lang='en', max_retries=MAX_RETRIES):
    """Translate text with retry mechanism."""
    for attempt in range(max_retries):
        try:
            translator = create_translator()
            
            # If source language is not provided, detect it
            if not source_lang:
                source_lang = detect_language_with_retry(text)
                if not source_lang:
                    raise Exception("Could not detect source language")

            # Validate target language
            if target_lang not in LANGUAGES:
                raise ValueError(f"Unsupported target language: {target_lang}")

            translation = translator.translate(text, src=source_lang, dest=target_lang)
            return {
                'text': translation.text,
                'source_lang': source_lang,
                'detected_source_lang': translation.src
            }
        except Exception as e:
            if attempt == max_retries - 1:
                print(f"Final translation error: {e}")
                return None
            print(f"Translation attempt {attempt + 1} failed: {e}")
            time.sleep(RETRY_DELAY)

# [Previous audio conversion functions remain the same]
def convert_audio_to_wav(audio_data):
    """Convert audio data to WAV format using FFmpeg."""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.webm') as temp_webm:
            temp_webm.write(audio_data)
            webm_path = temp_webm.name

        wav_path = webm_path + '.wav'

        command = [
            'ffmpeg',
            '-i', webm_path,
            '-acodec', 'pcm_s16le',
            '-ac', '1',
            '-ar', '16000',
            '-y',
            wav_path
        ]

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, stderr = process.communicate()

        if process.returncode != 0:
            print(f"FFmpeg error: {stderr.decode()}")
            raise Exception("FFmpeg conversion failed")

        os.unlink(webm_path)
        return wav_path
    except Exception as e:
        print(f"Error in convert_audio_to_wav: {e}")
        if 'webm_path' in locals() and os.path.exists(webm_path):
            os.unlink(webm_path)
        if 'wav_path' in locals() and os.path.exists(wav_path):
            os.unlink(wav_path)
        raise

def transcribe_audio(audio_path, language=None):
    """Transcribe audio file to text with optional language hint."""
    recognizer = sr.Recognizer()
    try:
        with sr.AudioFile(audio_path) as source:
            audio = recognizer.record(source)
            if language:
                text = recognizer.recognize_google(audio, language=language)
            else:
                text = recognizer.recognize_google(audio)
            return text
    except sr.UnknownValueError:
        print("Speech Recognition could not understand audio")
        return None
    except sr.RequestError as e:
        print(f"Could not request results from Speech Recognition service; {e}")
        return None
    except Exception as e:
        print(f"Error in transcribe_audio: {e}")
        return None

def generate_audio(text, lang):
    """Generate audio from text in specified language."""
    try:
        tts = gTTS(text=text, lang=lang)
        audio_io = io.BytesIO()
        tts.write_to_fp(audio_io)
        audio_io.seek(0)
        audio_data = base64.b64encode(audio_io.read()).decode('utf-8')
        return audio_data
    except Exception as e:
        print(f"Audio generation error: {e}")
        return None

@app.route('/')
def home():
    return send_from_directory('.', 'index.html')

@app.route('/translate', methods=['POST'])
def translate():
    wav_path = None
    try:
        if 'audio' not in request.files:
            return jsonify({'error': 'No audio file provided'}), 400

        audio_file = request.files['audio']
        if not audio_file.filename.endswith('.webm'):
            return jsonify({'error': 'Invalid audio format. Please send WebM audio.'}), 400

        source_lang = request.form.get('source_lang')
        target_lang = request.form.get('target_lang', 'en')

        wav_path = convert_audio_to_wav(audio_file.read())
        if not wav_path or not os.path.exists(wav_path):
            return jsonify({'error': 'Audio conversion failed'}), 400

        original_text = transcribe_audio(wav_path, source_lang)
        if not original_text:
            return jsonify({'error': 'Could not transcribe audio'}), 400

        translation_result = translate_text_with_retry(original_text, source_lang, target_lang)
        if not translation_result:
            return jsonify({'error': 'Translation service error. Please try again.'}), 500

        audio_data = generate_audio(translation_result['text'], target_lang)
        if not audio_data:
            return jsonify({'error': 'Could not generate audio'}), 400

        return jsonify({
            'original_text': original_text,
            'translated_text': translation_result['text'],
            'source_lang': translation_result['detected_source_lang'],
            'target_lang': target_lang,
            'audio_data': audio_data
        })

    except Exception as e:
        print(f"Error in translate route: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if wav_path and os.path.exists(wav_path):
            try:
                os.unlink(wav_path)
            except Exception as e:
                print(f"Error cleaning up WAV file: {e}")

@app.route('/supported_languages', methods=['GET'])
def get_supported_languages():
    """Return a list of supported languages for translation."""
    return jsonify(LANGUAGES)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port, debug=False)