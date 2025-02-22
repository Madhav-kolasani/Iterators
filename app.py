from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import speech_recognition as sr
from gtts import gTTS
from googletrans import Translator
import tempfile
import subprocess
import os
import io
import base64

app = Flask(__name__)
CORS(app)

@app.route('/')
def home():
    return send_file('index.html')

def convert_audio_to_wav(audio_data):
    """Convert audio data to WAV format using FFmpeg."""
    try:
        # Create temporary files
        with tempfile.NamedTemporaryFile(delete=False, suffix='.webm') as temp_webm:
            temp_webm.write(audio_data)
            webm_path = temp_webm.name

        wav_path = webm_path + '.wav'

        # Use FFmpeg to convert to WAV
        command = [
            'ffmpeg',
            '-i', webm_path,  # Input file
            '-acodec', 'pcm_s16le',  # Audio codec
            '-ac', '1',  # Mono audio
            '-ar', '16000',  # Sample rate
            '-y',  # Overwrite output file if it exists
            wav_path  # Output file
        ]

        # Run FFmpeg command
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, stderr = process.communicate()

        if process.returncode != 0:
            print(f"FFmpeg error: {stderr.decode()}")
            raise Exception("FFmpeg conversion failed")

        # Clean up the webm file
        os.unlink(webm_path)

        return wav_path
    except Exception as e:
        print(f"Error in convert_audio_to_wav: {e}")
        if 'webm_path' in locals() and os.path.exists(webm_path):
            os.unlink(webm_path)
        if 'wav_path' in locals() and os.path.exists(wav_path):
            os.unlink(wav_path)
        raise

def detect_language(text):
    """Detect the language of the input text."""
    try:
        translator = Translator()
        detection = translator.detect(text)
        return detection.lang
    except Exception as e:
        print(f"Language detection error: {e}")
        return None

def transcribe_audio(audio_path, language=None):
    """Transcribe audio file to text with optional language hint."""
    recognizer = sr.Recognizer()
    try:
        with sr.AudioFile(audio_path) as source:
            audio = recognizer.record(source)
            # If language is provided, use it as a hint for speech recognition
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

def translate_text(text, source_lang=None, target_lang='en'):
    """Translate text from source language to target language."""
    translator = Translator()
    try:
        # If source language is not provided, detect it
        if not source_lang:
            source_lang = detect_language(text)
            if not source_lang:
                raise Exception("Could not detect source language")

        translation = translator.translate(text, src=source_lang, dest=target_lang)
        return {
            'text': translation.text,
            'source_lang': source_lang,
            'detected_source_lang': translation.src
        }
    except Exception as e:
        print(f"Translation error: {e}")
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

@app.route('/translate', methods=['POST'])
def translate():
    wav_path = None
    try:
        if 'audio' not in request.files:
            return jsonify({'error': 'No audio file provided'}), 400

        audio_file = request.files['audio']
        if not audio_file.filename.endswith('.webm'):
            return jsonify({'error': 'Invalid audio format. Please send WebM audio.'}), 400

        # Get source and target languages from request
        source_lang = request.form.get('source_lang')  # Optional
        target_lang = request.form.get('target_lang', 'en')  # Default to English if not specified

        # Convert audio to WAV
        wav_path = convert_audio_to_wav(audio_file.read())
        if not wav_path or not os.path.exists(wav_path):
            return jsonify({'error': 'Audio conversion failed'}), 400

        # Transcribe audio to text with language hint if provided
        original_text = transcribe_audio(wav_path, source_lang)
        if not original_text:
            return jsonify({'error': 'Could not transcribe audio'}), 400

        # Translate text
        translation_result = translate_text(original_text, source_lang, target_lang)
        if not translation_result:
            return jsonify({'error': 'Could not translate text'}), 400

        # Generate audio for translated text
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
        # Clean up temporary files
        if wav_path and os.path.exists(wav_path):
            try:
                os.unlink(wav_path)
            except Exception as e:
                print(f"Error cleaning up WAV file: {e}")

@app.route('/supported_languages', methods=['GET'])
def get_supported_languages():
    """Return a list of supported languages for translation."""
    # This is a simplified list. You may want to get this dynamically from the translation service
    supported_languages = {
        'en': 'English',
        'es': 'Spanish',
        'fr': 'French',
        'de': 'German',
        'it': 'Italian',
        'pt': 'Portuguese',
        'ru': 'Russian',
        'ja': 'Japanese',
        'ko': 'Korean',
        'zh-cn': 'Chinese (Simplified)',
        'ar': 'Arabic',
        'hi': 'Hindi'
    }
    return jsonify(supported_languages)

if __name__ == '__main__':
    app.run(debug=True)