/**
 * Client-side image resize for chat upload.
 *
 * Sprint D6.97 Phase 2 — every uploaded image is constrained to fit
 * within a MAX_DIMENSION × MAX_DIMENSION box (long-edge clamp,
 * aspect-ratio preserved). When a resize is actually needed we
 * re-encode as JPEG q0.9. When the source is ALREADY within the
 * Anthropic-optimal envelope (long edge ≤ 1568px) we skip the canvas
 * round-trip entirely and ship the original bytes verbatim — phone
 * screenshots, the most common maritime-doc upload format, stay
 * pixel-perfect.
 *
 * Why 1568 and not 1024:
 *   Anthropic's vision API internally downsamples anything above
 *   ~1568px on the long edge. Below that, every pixel of detail
 *   reaches the model. The pre-tune setting (1024 / q0.8) was a
 *   premature cost optimization — it stripped legible-text detail
 *   from regulation screenshots, vessel docs, and hazmat labels with
 *   no Anthropic-side benefit. Cost delta: ~3× per image, ~$0.01
 *   on a single-image query at Sonnet rates. Negligible.
 *
 * Why JPEG q0.9 (not q0.8):
 *   q0.8 introduces visible ringing around text edges that the model
 *   has to "guess through." q0.9 keeps text crisp at ~15-25% size
 *   premium — well worth it for a document-heavy use case.
 *
 * Why preserve originals when small:
 *   A phone screenshot at 1284×2778 PNG re-encoded as 1284×2778
 *   JPEG q0.9 loses fidelity to no purpose — the source was already
 *   below the API's downsample threshold. Skip-resize-and-re-encode
 *   passes the PNG through untouched.
 */

export interface ResizedImage {
  data_url: string  // "data:image/jpeg;base64,..." | "data:image/png;base64,..." | "data:image/webp;base64,..."
  width: number     // pixel width AT THE WIRE (post-resize, or source if skipped)
  height: number    // pixel height AT THE WIRE
  size_bytes: number  // approximate decoded byte length
}

// D6.97 Phase 2 tune (2026-05-20): 1024 → 1568 to match Anthropic's
// internal vision-input ceiling. No benefit going higher (the API
// resizes); meaningful detail loss going lower.
export const MAX_DIMENSION = 1568
// D6.97 Phase 2 tune (2026-05-20): 0.8 → 0.9 for text-edge fidelity.
export const JPEG_QUALITY = 0.9
export const ALLOWED_MIME = new Set([
  'image/jpeg',
  'image/png',
  'image/webp',
])
// 25 MB raw input cap. After resize-or-skip, the resulting payload
// lands under the 10 MB per-image server cap in practice (phone JPEGs
// at 1568 q0.9 are 200 KB – 1.5 MB; native screenshots stay similar).
export const MAX_INPUT_BYTES = 25 * 1024 * 1024

export class ImageRejectedError extends Error {
  constructor(public reason: string, message: string) {
    super(message)
    this.name = 'ImageRejectedError'
  }
}

/**
 * Resize a File for chat upload.
 *
 * Decision tree:
 *   1. MIME not in allowlist                → reject
 *   2. Raw size > MAX_INPUT_BYTES (25 MB)   → reject
 *   3. Source dims ≤ MAX_DIMENSION on both edges → skip canvas, return
 *      original bytes as data URL (preserves PNG/WebP losslessly)
 *   4. Otherwise: scale to MAX_DIMENSION long edge via canvas, encode
 *      as JPEG q0.9
 *
 * Throws ImageRejectedError on invalid inputs (wrong MIME, too large,
 * decode failure). Caller surfaces the reason to the user.
 */
export async function resizeImageForChat(file: File): Promise<ResizedImage> {
  if (!ALLOWED_MIME.has(file.type)) {
    throw new ImageRejectedError(
      'unsupported_type',
      `${file.name}: ${file.type || 'unknown'} not supported (allowed: JPEG, PNG, WebP).`,
    )
  }
  if (file.size > MAX_INPUT_BYTES) {
    const mb = (file.size / (1024 * 1024)).toFixed(1)
    throw new ImageRejectedError(
      'too_large',
      `${file.name}: ${mb} MB exceeds 25 MB input limit.`,
    )
  }

  // Measure source dims so we can decide between skip-resize and the
  // canvas path. loadImage is cheap (browser's native decoder).
  const bitmap = await loadImage(file)
  const srcW = bitmap.width
  const srcH = bitmap.height
  const needsResize = srcW > MAX_DIMENSION || srcH > MAX_DIMENSION

  // ── Skip-resize fast path ────────────────────────────────────────
  // Source already within Anthropic's vision-optimal envelope. Ship
  // the original bytes verbatim — no canvas round-trip, no lossy
  // re-encode. PNG stays PNG; WebP stays WebP; JPEG stays JPEG at
  // its original quality.
  if (!needsResize) {
    const dataUrl = await fileToDataUrl(file)
    return {
      data_url: dataUrl,
      width: srcW,
      height: srcH,
      size_bytes: file.size,
    }
  }

  // ── Resize path ──────────────────────────────────────────────────
  // Long edge clamped to MAX_DIMENSION, aspect ratio preserved.
  let width = srcW
  let height = srcH
  if (width >= height) {
    height = Math.round((height * MAX_DIMENSION) / width)
    width = MAX_DIMENSION
  } else {
    width = Math.round((width * MAX_DIMENSION) / height)
    height = MAX_DIMENSION
  }

  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')
  if (!ctx) {
    throw new ImageRejectedError('canvas_unavailable', 'Browser canvas unavailable.')
  }
  ctx.drawImage(bitmap, 0, 0, width, height)

  // Resized output is always JPEG q0.9. Even if the source was PNG,
  // we're past the API downsample threshold so we're already paying
  // a quality tax — JPEG keeps file size sane (PNGs of large photos
  // can be 5-10× a JPEG of equal visual quality).
  const dataUrl = canvas.toDataURL('image/jpeg', JPEG_QUALITY)

  // Estimate decoded size: base64 portion is ~4/3 of the original
  // byte count.
  const base64Portion = dataUrl.split(',', 2)[1] || ''
  const sizeBytes = Math.round(base64Portion.length * 0.75)

  return {
    data_url: dataUrl,
    width,
    height,
    size_bytes: sizeBytes,
  }

  function loadImage(f: File): Promise<HTMLImageElement> {
    return new Promise((resolve, reject) => {
      const img = new Image()
      const url = URL.createObjectURL(f)
      img.onload = () => {
        URL.revokeObjectURL(url)
        resolve(img)
      }
      img.onerror = () => {
        URL.revokeObjectURL(url)
        reject(new ImageRejectedError('decode_failed', `${f.name}: failed to decode image.`))
      }
      img.src = url
    })
  }

  function fileToDataUrl(f: File): Promise<string> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => {
        const result = reader.result
        if (typeof result !== 'string') {
          reject(new ImageRejectedError('read_failed', `${f.name}: unexpected read result.`))
          return
        }
        resolve(result)
      }
      reader.onerror = () => {
        reject(new ImageRejectedError('read_failed', `${f.name}: failed to read file.`))
      }
      reader.readAsDataURL(f)
    })
  }
}
