/**
 * Client-side image resize for chat upload.
 *
 * Sprint D6.97 Phase 2 — every uploaded image is resized to fit inside
 * a 1024×1024 box (long-edge constraint, preserving aspect ratio) and
 * re-encoded as JPEG quality 0.8. Result: typical phone photo (~3-4 MB)
 * lands at 200-500 KB, well under the 10 MB server cap.
 *
 * Why client-side:
 *   1. Cheap (canvas + toDataURL is fast on modern devices).
 *   2. Reduces upload bandwidth — important on mobile.
 *   3. Keeps the Anthropic vision API payload small (their pricing is
 *      per-image-token, but smaller dimensions = fewer tokens).
 *
 * Why JPEG 0.8:
 *   PNG would preserve fidelity but blow up sizes 5-10× for photos.
 *   For maritime use cases (vessel docs, regulation screenshots,
 *   equipment photos) JPEG 0.8 is visually indistinguishable from
 *   source while landing in the 200-500 KB range.
 *
 * Returns a structure compatible with the backend's ChatImageInput.
 */

export interface ResizedImage {
  data_url: string  // "data:image/jpeg;base64,..." or "data:image/png;base64,..."
  width: number     // post-resize pixel width
  height: number    // post-resize pixel height
  size_bytes: number  // approximate decoded size (base64 length × 0.75)
}

export const MAX_DIMENSION = 1024
export const JPEG_QUALITY = 0.8
export const ALLOWED_MIME = new Set([
  'image/jpeg',
  'image/png',
  'image/webp',
])
export const MAX_INPUT_BYTES = 25 * 1024 * 1024  // 25 MB raw input cap

export class ImageRejectedError extends Error {
  constructor(public reason: string, message: string) {
    super(message)
    this.name = 'ImageRejectedError'
  }
}

/**
 * Resize a File to fit within MAX_DIMENSION × MAX_DIMENSION, preserving
 * aspect ratio. Output is JPEG unless the input is PNG (preserved to
 * keep alpha channel) — but PNGs above 512×512 get rescaled to JPEG to
 * avoid token bloat on common screenshot resolutions.
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

  // Decode into an HTMLImageElement so we can measure + draw onto canvas.
  const bitmap = await loadImage(file)

  // Compute target dimensions — long edge clamped to MAX_DIMENSION.
  let { width, height } = bitmap
  if (width > MAX_DIMENSION || height > MAX_DIMENSION) {
    if (width >= height) {
      height = Math.round((height * MAX_DIMENSION) / width)
      width = MAX_DIMENSION
    } else {
      width = Math.round((width * MAX_DIMENSION) / height)
      height = MAX_DIMENSION
    }
  }

  // Draw to canvas + re-encode.
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')
  if (!ctx) {
    throw new ImageRejectedError('canvas_unavailable', 'Browser canvas unavailable.')
  }
  ctx.drawImage(bitmap, 0, 0, width, height)

  // Preserve PNG only when the input was PNG AND the image is small
  // enough that the size penalty is acceptable. Otherwise re-encode JPEG.
  const preservePng = file.type === 'image/png' && width * height <= 512 * 512
  const outMime = preservePng ? 'image/png' : 'image/jpeg'
  const dataUrl = preservePng
    ? canvas.toDataURL('image/png')
    : canvas.toDataURL('image/jpeg', JPEG_QUALITY)

  // Estimate decoded size: base64 portion is ~4/3 the original byte count.
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
}
