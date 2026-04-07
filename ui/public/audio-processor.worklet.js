/**
 * Audio Processing Worklet for VoiceClonePanel
 * Replaces deprecated ScriptProcessorNode with AudioWorkletNode
 *
 * This worklet runs on a separate audio thread, providing:
 * - Better performance (no main thread blocking)
 * - Lower latency audio processing
 * - Modern Web Audio API compliance
 */
class AudioCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._buffer = [];
  }

  /**
   * @param {AudioProcessEvent} event
   * @returns {boolean}
   */
  process(inputs, outputs, parameters) {
    const input = inputs[0];
    if (!input || !input[0]) {
      return true;
    }

    const channelData = input[0];

    // Send raw Float32Array samples to the main thread via port
    this.port.postMessage({
      type: 'audio-data',
      samples: channelData
    });

    return true;
  }
}

registerProcessor('audio-capture-processor', AudioCaptureProcessor);
