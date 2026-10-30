export type MediaPreview = {
  type: 'image' | 'audio' | 'video'
  url: string
  name: string
}

export function getMediaPreviews(fields: Record<string, unknown>): MediaPreview[] {
  const previews: MediaPreview[] = []
  for (const [key, value] of Object.entries(fields)) {
    const normalizedKey = key.toLowerCase()
    const keyType = normalizedKey.includes('image') || normalizedKey.includes('photo')
      ? 'image'
      : normalizedKey.includes('audio') || normalizedKey.includes('sound')
        ? 'audio'
        : normalizedKey.includes('video')
          ? 'video'
          : null
    const candidates = Array.isArray(value) ? value : [value]
    for (const candidate of candidates) {
      const url =
        typeof candidate === 'string'
          ? candidate
          : typeof candidate === 'object' &&
              candidate !== null &&
              'url' in candidate &&
              typeof candidate.url === 'string'
            ? candidate.url
            : ''
      if (!url) continue
      const candidateType =
        typeof candidate === 'object' && candidate !== null
          ? 'type' in candidate && typeof candidate.type === 'string'
            ? candidate.type.toLowerCase()
            : 'content_type' in candidate && typeof candidate.content_type === 'string'
              ? candidate.content_type.toLowerCase()
              : ''
          : ''
      const type = keyType ??
        (candidateType.startsWith('image') ? 'image' :
          candidateType.startsWith('audio') ? 'audio' :
            candidateType.startsWith('video') ? 'video' : null)
      if (!type) continue
      try {
        const parsed = new URL(url, window.location.origin)
        if (parsed.origin !== window.location.origin) continue
        previews.push({ type, url: parsed.href, name: key })
      } catch {
        continue
      }
    }
  }
  return previews
}
