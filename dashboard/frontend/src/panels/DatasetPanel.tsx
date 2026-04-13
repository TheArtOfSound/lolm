import { useState } from 'react'
import { Database, ExternalLink } from 'lucide-react'
import Card from '../components/Card'

const DATASETS = [
  { id: 'HuggingFaceFW/fineweb-edu', name: 'FineWeb-Edu', tokens: '1.3T', category: 'Pretraining', desc: 'Curated educational web corpus. LOLM primary training data.' },
  { id: 'allenai/c4', name: 'C4', tokens: '156B', category: 'Pretraining', desc: 'Colossal Clean Crawled Corpus — filtered Common Crawl web text.' },
  { id: 'togethercomputer/RedPajama-Data-1T', name: 'RedPajama', tokens: '1.2T', category: 'Pretraining', desc: 'Open reproduction of LLaMA training data mix.' },
  { id: 'EleutherAI/pile', name: 'The Pile', tokens: '825GB', category: 'Pretraining', desc: 'Diverse 22-domain dataset. Pythia training data.' },
  { id: 'roneneldan/TinyStories', name: 'TinyStories', tokens: '~500M', category: 'Testing', desc: 'Small stories dataset for fast ablations (LOLM 20.5M trained on this).' },
  { id: 'wikitext/wikitext-103-v1', name: 'WikiText-103', tokens: '103M', category: 'Eval', desc: 'Standard benchmark. LOLM-304M eval: 68.37 PPL.' },
  { id: 'bigcode/the-stack', name: 'The Stack', tokens: '6TB', category: 'Code', desc: 'Permissively licensed code across 30+ languages.' },
  { id: 'pubmed', name: 'PubMed Abstracts', tokens: '~15B', category: 'Domain', desc: 'Biomedical literature abstracts.' },
]

export default function DatasetPanel() {
  const [selected, setSelected] = useState('HuggingFaceFW/fineweb-edu')
  const [customDataset, setCustomDataset] = useState('')
  const [tokenizer, setTokenizer] = useState('gpt2')

  const categories = [...new Set(DATASETS.map(d => d.category))]

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-bold">Dataset Selection</h2>

      {categories.map(cat => (
        <Card key={cat} title={cat}>
          <div className="space-y-2">
            {DATASETS.filter(d => d.category === cat).map(ds => (
              <label key={ds.id}
                className={`flex items-start gap-3 p-3 rounded cursor-pointer transition-all ${
                  selected === ds.id ? 'bg-accent/10 border border-accent/30' : 'hover:bg-surface-2 border border-transparent'
                }`}>
                <input type="radio" name="dataset" checked={selected === ds.id}
                  onChange={() => setSelected(ds.id)} className="accent-accent mt-1" />
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-white">{ds.name}</span>
                    <span className="text-[10px] text-muted bg-surface-2 px-1.5 py-0.5 rounded">{ds.tokens} tokens</span>
                  </div>
                  <p className="text-[11px] text-muted mt-0.5">{ds.desc}</p>
                  <p className="text-[10px] text-muted/50 mt-0.5 font-mono">{ds.id}</p>
                </div>
              </label>
            ))}
          </div>
        </Card>
      ))}

      <Card title="Custom Dataset">
        <div className="space-y-3">
          <div>
            <label className="text-[10px] text-muted block mb-1">HuggingFace dataset path or local path</label>
            <input value={customDataset} onChange={e => setCustomDataset(e.target.value)}
              placeholder="username/dataset-name or /path/to/local/*.parquet"
              className="w-full bg-bg border border-border rounded px-3 py-2 text-xs text-white" />
          </div>
          <div>
            <label className="text-[10px] text-muted block mb-1">Tokenizer</label>
            <select value={tokenizer} onChange={e => setTokenizer(e.target.value)}
              className="bg-bg border border-border rounded px-3 py-2 text-xs text-white">
              <option value="gpt2">GPT-2 BPE (50257 tokens)</option>
              <option value="cl100k_base">cl100k_base (100K tokens, GPT-4)</option>
            </select>
          </div>
        </div>
      </Card>

      <Card title="Current Selection">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Database size={16} className="text-accent" />
            <div>
              <span className="text-xs text-white font-medium">{selected || customDataset || 'None'}</span>
              <span className="text-xs text-muted ml-2">• Tokenizer: {tokenizer}</span>
            </div>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => {
                localStorage.setItem('lolm_dataset', selected || customDataset)
                localStorage.setItem('lolm_tokenizer', tokenizer)
                alert(`Dataset saved!\n\n${selected || customDataset}\nTokenizer: ${tokenizer}\n\nThis will be used for the next training launch from Quick Launch.`)
              }}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-accent text-white text-xs font-semibold rounded hover:bg-accent-2"
            >
              Apply & Save
            </button>
          </div>
        </div>
        <p className="text-[10px] text-muted mt-2">
          Click "Apply & Save" to set this as the default dataset. Quick Launch will use this dataset for all new training runs.
        </p>
      </Card>
    </div>
  )
}
