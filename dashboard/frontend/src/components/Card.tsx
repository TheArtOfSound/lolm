interface CardProps {
  title?: string
  children: React.ReactNode
  className?: string
}

export default function Card({ title, children, className = '' }: CardProps) {
  return (
    <div className={`bg-surface border border-border rounded-lg ${className}`}>
      {title && (
        <div className="px-4 py-3 border-b border-border">
          <h3 className="text-xs font-semibold text-white tracking-wide">{title}</h3>
        </div>
      )}
      <div className="p-4">{children}</div>
    </div>
  )
}
