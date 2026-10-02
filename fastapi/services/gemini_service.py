import os
import json
import logging
import google.generativeai as genai
import re
logger = logging.getLogger("siparta.gemini_service")

_GEMINI_CONFIGURED = False

def _ensure_configured():
    global _GEMINI_CONFIGURED
    if not _GEMINI_CONFIGURED:
        api_key = os.getenv("GEMINI_API_KEY", "")
        if api_key:
            genai.configure(api_key=api_key)
            _GEMINI_CONFIGURED = True
        else:
            logger.warning("[GEMINI] GEMINI_API_KEY tidak ditemukan di environment.")

def analyze_incident_with_gemini(sensor_data: dict, image_path: str):
    """
    Meneruskan foto dari RPi dan data telemetri ke Google Gemini.
    Tujuannya untuk memberikan rekomendasi mitigasi keselamatan (Evakuasi/Penanganan).
    """
    logger.info("[GEMINI] Meminta analisis Keselamatan dari Google...")
    _ensure_configured()
    
    # ── Fallback Message Dinamis ──
    fallback_msg = "Gagal mendapatkan analisis AI. Terapkan protokol evakuasi standar."
    if sensor_data.get('status') == 'BAHAYA':
        fallback_msg = "SISTEM AI GAGAL TERHUBUNG. STATUS BAHAYA. SEGERA EVAKUASI DAN HUBUNGI PEMADAM KEBAKARAN/TIM TANGGAP DARURAT!"
    elif sensor_data.get('status') == 'AMAN':
        fallback_msg = "Sistem AI tidak dapat diakses. Namun, indikator sensor menunjukkan status AMAN."

    try:
        # System Instruction untuk mengunci persona AI agar aman dan tidak berbahaya
        system_instruction = (
            "Anda adalah AI Keselamatan Darurat SIPARTA (Sistem Pintar Deteksi Kimia). "
            "Tugas utama Anda adalah memberikan panduan mitigasi keselamatan yang sangat konservatif dan defensif. "
            "Aturan ketat yang TIDAK BOLEH dilanggar: "
            "1. JANGAN PERNAH menyarankan eksperimen kimia, manipulasi, pembuatan, pencampuran, atau penetralan zat kimia secara mandiri. "
            "2. JIKA mendeteksi bahaya tinggi (Amonia, Karbon Monoksida tinggi, Gas mudah terbakar), prioritas UTAMA adalah EVAKUASI dan menjauh dari sumber. "
            "3. JANGAN menyarankan pengguna untuk menyentuh, mendekati, atau mematikan kebocoran secara langsung tanpa APD profesional. "
            "4. Jika data sensor bertentangan, ambigu, atau tidak wajar, instruksikan pengguna untuk mengandalkan alarm fisik dan segera menjauh. "
            "5. Hindari diagnosis kepastian medis; arahkan pengguna untuk mencari bantuan medis (P3K) jika terpapar."
        )

        model = genai.GenerativeModel(
            model_name='gemini-3.8-flash',
            system_instruction=system_instruction
        )
        
        # Mapping sensor untuk memandu AI
        prompt = f"""
        [SISTEM DARURAT SIPARTA]
        Status Bahaya: {sensor_data['status']}
        Waktu Kejadian: {sensor_data['timestamp']}
        
        [PANDUAN REFERENSI SENSOR (Hanya Info Pendukung)]
        - MICS-5524 : Mengukur Karbon Monoksida (CO) dan Gas Mudah Terbakar.
        - TGS2600   : Mengukur Polutan Udara (VOC Ringan, Metana, Isobutana).
        - MQ-2      : Mengukur Asap, Propana, Hidrogen (H2).
        - MQ-135    : Mengukur Amonia (NH3), Benzena, Hidrogen Sulfida (H2S), CO2.
        *Catatan: Nilai di atas 2.0V mengindikasikan kehadiran gas secara signifikan.
        
        [DATA PEMBACAAN SENSOR SAAT INI (Tegangan Output ADC)]
        - MICS-5524 : {sensor_data['sensors'].get('mics5524', 0)} Volt
        - TGS2600   : {sensor_data['sensors'].get('tgs2600', 0)} Volt
        - MQ-2      : {sensor_data['sensors'].get('mq2', 0)} Volt
        - MQ-135    : {sensor_data['sensors'].get('mq135', 0)} Volt
        
        Tugas Anda:
        1. Analisis gambar terlampir (foto lokasi kejadian) jika relevan. Adakah asap tebal, sumber api, atau hal mencurigakan? (Jangan berasumsi berlebihan jika gambar gelap/kabur, andalkan data sensor).
        2. Berdasarkan pembacaan sensor dan status '{sensor_data['status']}', gas berbahaya apa yang paling mungkin sedang mencemari ruangan?
        3. Berikan maksimal 3 poin singkat (tiap poin max 2 kalimat) rekomendasi tindakan mitigasi, perlindungan diri, atau evakuasi! 
        """
        
        # Upload file gambar barang bukti (jika ada)
        contents = []
        if image_path and os.path.exists(image_path):
            sample_file = genai.upload_file(path=image_path, display_name="SIPARTA_Incident_Visual")
            contents.append(sample_file)
        
        contents.append(prompt)
        
        response = model.generate_content(contents)
        return response.text
        
    except Exception as e:
        logger.error(f"[GEMINI] Gagal memanggil API: {e}")
        return fallback_msg

def extract_sensor_data_from_image(image_path: str) -> dict:
    """
    Extracts sensor readings from a photo (e.g. from DroidCam) using Gemini OCR.
    Returns a dict with mics5524, tgs2600, mq2, mq135 as floats.
    """
    logger.info("[GEMINI] Scraping sensor data dari gambar...")
    _ensure_configured()
    
    if not image_path or not os.path.exists(image_path):
        raise ValueError("Image path is invalid or does not exist.")
        
    try:
        system_instruction = (
            "Anda adalah asisten data extraction OCR. "
            "Tugas Anda adalah membaca angka dari gambar layar (tegangan sensor gas). "
            "Ada 4 sensor: MICS-5524, TGS2600, MQ-2, dan MQ-135. "
            "Ekstrak nilai angka tegangan (biasanya format 0.00 hingga 5.00) untuk masing-masing sensor. "
            "Kembalikan HANYA JSON block murni tanpa markdown, dengan format persis: "
            "{\"mics5524\": float, \"tgs2600\": float, \"mq2\": float, \"mq135\": float}. "
            "Jika Anda tidak bisa melihat angka tertentu, berikan nilai 0.0."
        )
        model = genai.GenerativeModel(
            model_name='gemini-3.8-flash',
            system_instruction=system_instruction
        )
        
        sample_file = genai.upload_file(path=image_path, display_name="SIPARTA_Sensor_Screen")
        prompt = "Ekstrak nilai keempat sensor tersebut dalam format JSON."
        
        response = model.generate_content([sample_file, prompt])
        text_response = response.text.strip()
        
        # Bersihkan markdown HANYA JIKA ADA
        text_response = re.sub(r'```(?:json)?', '', text_response).strip()
        text_response = re.sub(r'```', '', text_response).strip()
        
        data = json.loads(text_response)
        
        # Validasi format
        return {
            "mics5524": float(data.get("mics5524", 0.0)),
            "tgs2600": float(data.get("tgs2600", 0.0)),
            "mq2": float(data.get("mq2", 0.0)),
            "mq135": float(data.get("mq135", 0.0))
        }
    except Exception as e:
        logger.error(f"[GEMINI] Gagal ekstrak data sensor dari gambar: {e}")
        raise

