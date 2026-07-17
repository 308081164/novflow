type BrandMarkProps = {
  /** icon = square app mark; logo = horizontal wordmark */
  variant?: "icon" | "logo"
  className?: string
  alt?: string
}

/** Official NovFlow brand mark from /public assets. */
export default function BrandMark({
  variant = "icon",
  className = "",
  alt = "NovFlow",
}: BrandMarkProps) {
  const src = variant === "logo" ? "/logo.png" : "/icon.png"
  return (
    <img
      src={src}
      alt={alt}
      className={className}
      draggable={false}
    />
  )
}
