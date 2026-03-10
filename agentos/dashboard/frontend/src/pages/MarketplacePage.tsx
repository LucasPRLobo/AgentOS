import { useCallback, useEffect, useState } from 'react'

interface Template {
  template_id: string
  name: string
  description: string
  author: string
  category: string
  tags: string[]
  verified: boolean
  downloads: number
  metrics: {
    avg_cost_usd: number
    avg_duration_seconds: number
    approval_rate: number
    completion_rate: number
    total_runs: number
  }
}

interface MarketplacePageProps {
  apiBase?: string
}

export function MarketplacePage({ apiBase = '/api' }: MarketplacePageProps) {
  const [templates, setTemplates] = useState<Template[]>([])
  const [filter, setFilter] = useState('')
  const [category, setCategory] = useState<string>('all')
  const [verifiedOnly, setVerifiedOnly] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchTemplates = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      if (category !== 'all') params.set('category', category)
      if (verifiedOnly) params.set('verified_only', 'true')
      const res = await fetch(`${apiBase}/marketplace/templates?${params}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setTemplates(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load templates')
    } finally {
      setLoading(false)
    }
  }, [apiBase, category, verifiedOnly])

  useEffect(() => {
    fetchTemplates()
  }, [fetchTemplates])

  const handleDeploy = useCallback(
    async (templateId: string) => {
      try {
        const res = await fetch(`${apiBase}/marketplace/templates/${templateId}/deploy`, {
          method: 'POST',
        })
        if (!res.ok) throw new Error(`Deploy failed: HTTP ${res.status}`)
        fetchTemplates()
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Deploy failed')
      }
    },
    [apiBase, fetchTemplates]
  )

  const filtered = templates.filter(
    (t) =>
      t.name.toLowerCase().includes(filter.toLowerCase()) ||
      t.description.toLowerCase().includes(filter.toLowerCase()) ||
      t.tags.some((tag) => tag.toLowerCase().includes(filter.toLowerCase()))
  )

  return (
    <div className="marketplace-page" data-testid="marketplace-page">
      <div className="marketplace-header">
        <h2>Workflow Marketplace</h2>
        <div className="marketplace-filters">
          <input
            type="text"
            placeholder="Search templates..."
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            data-testid="marketplace-search"
          />
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            data-testid="marketplace-category"
          >
            <option value="all">All Categories</option>
            <option value="research">Research</option>
            <option value="devops">DevOps</option>
            <option value="finance">Finance</option>
            <option value="general">General</option>
          </select>
          <label data-testid="verified-filter">
            <input
              type="checkbox"
              checked={verifiedOnly}
              onChange={(e) => setVerifiedOnly(e.target.checked)}
            />
            Verified only
          </label>
        </div>
      </div>

      {loading && <div data-testid="loading">Loading...</div>}
      {error && <div className="error" data-testid="error">{error}</div>}

      <div className="template-grid" data-testid="template-grid">
        {filtered.map((template) => (
          <div
            key={template.template_id}
            className="template-card"
            data-testid={`template-card-${template.template_id}`}
          >
            <div className="template-header">
              <h3>{template.name}</h3>
              {template.verified && (
                <span className="verified-badge" data-testid="verified-badge">
                  Verified
                </span>
              )}
            </div>
            <p className="template-desc">{template.description}</p>
            <div className="template-meta">
              <span>by {template.author || 'Anonymous'}</span>
              <span>{template.downloads} downloads</span>
            </div>
            <div className="template-metrics">
              {template.metrics.total_runs > 0 && (
                <>
                  <span>Cost: ${template.metrics.avg_cost_usd.toFixed(2)}</span>
                  <span>Duration: {template.metrics.avg_duration_seconds.toFixed(0)}s</span>
                  <span>Approval: {(template.metrics.approval_rate * 100).toFixed(0)}%</span>
                </>
              )}
            </div>
            <div className="template-tags">
              {template.tags.map((tag) => (
                <span key={tag} className="tag">
                  {tag}
                </span>
              ))}
            </div>
            <button
              className="deploy-btn"
              data-testid={`deploy-${template.template_id}`}
              onClick={() => handleDeploy(template.template_id)}
            >
              Deploy
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}
