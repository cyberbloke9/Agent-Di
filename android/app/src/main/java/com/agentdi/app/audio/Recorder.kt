package com.agentdi.app.audio

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import java.io.ByteArrayOutputStream

/**
 * Records microphone audio into a 16 kHz mono 16-bit WAV byte array — the format
 * Sarvam's ASR accepts — using only the Android SDK (AudioRecord), no deps.
 *
 * Usage: create, start() on a worker thread, stop() to get the WAV bytes. Nothing
 * is written to disk; the bytes go straight to the server and are not retained.
 * The caller must hold RECORD_AUDIO before start().
 */
class Recorder {
    private var record: AudioRecord? = null
    @Volatile private var recording = false

    companion object {
        const val SAMPLE_RATE = 16000
    }

    /** Blocks on the calling (worker) thread, capturing until stop() is called. */
    @SuppressLint("MissingPermission") // caller checks RECORD_AUDIO before start()
    fun start(): ByteArray {
        val minBuf = AudioRecord.getMinBufferSize(
            SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT
        )
        val bufSize = if (minBuf > 0) minBuf * 2 else SAMPLE_RATE * 2
        val rec = AudioRecord(
            MediaRecorder.AudioSource.MIC, SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, bufSize
        )
        record = rec
        val pcm = ByteArrayOutputStream()
        val buf = ByteArray(bufSize)
        recording = true
        rec.startRecording()
        try {
            while (recording) {
                val n = rec.read(buf, 0, buf.size)
                if (n > 0) pcm.write(buf, 0, n)
            }
        } finally {
            try { rec.stop() } catch (_: Exception) {}
            rec.release()
            record = null
        }
        return wrapWav(pcm.toByteArray(), SAMPLE_RATE, 1, 16)
    }

    /** Signals start()'s loop to finish; the WAV bytes are returned from start(). */
    fun stop() { recording = false }

    val isRecording: Boolean get() = recording
}

/** Prepend a 44-byte WAV/PCM header to raw little-endian PCM samples. */
private fun wrapWav(pcm: ByteArray, sampleRate: Int, channels: Int, bits: Int): ByteArray {
    val byteRate = sampleRate * channels * bits / 8
    val blockAlign = channels * bits / 8
    val dataLen = pcm.size
    val out = ByteArrayOutputStream(44 + dataLen)

    fun str(s: String) = out.write(s.toByteArray(Charsets.US_ASCII))
    fun i32(v: Int) { out.write(v and 0xff); out.write((v ushr 8) and 0xff); out.write((v ushr 16) and 0xff); out.write((v ushr 24) and 0xff) }
    fun i16(v: Int) { out.write(v and 0xff); out.write((v ushr 8) and 0xff) }

    str("RIFF"); i32(36 + dataLen); str("WAVE")
    str("fmt "); i32(16); i16(1); i16(channels)
    i32(sampleRate); i32(byteRate); i16(blockAlign); i16(bits)
    str("data"); i32(dataLen)
    out.write(pcm)
    return out.toByteArray()
}
