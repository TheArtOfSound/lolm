"""LOLM Chat Server — serves inference from latest checkpoint."""
import sys, os, json, torch, tiktoken
from http.server import HTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, os.path.expanduser("~/Documents/Latent"))
from lolm.config import load_config
from lolm.model import LOLM

CKPT = os.path.expanduser("~/Documents/Latent/tpu_results/full_lolm/ckpt_35000.pt")
CFG = os.path.expanduser("~/Documents/Latent/configs/scale/300m_lolm_full_tpu.yaml")

print("Loading LOLM...")
cfg = load_config(CFG)
model = LOLM(cfg.model)
for name, param in model.named_parameters():
    if "A_log" in name:
        param.data = param.data.clone()
ckpt = torch.load(CKPT, map_location="cpu", weights_only=False)
state = {k: v.clone() for k, v in ckpt["model"].items()}
model.load_state_dict(state, strict=False)
model.eval()
step = ckpt.get("step", "?")
params = sum(p.numel() for p in model.parameters())
enc = tiktoken.get_encoding("gpt2")
print(f"LOLM loaded: {params:,} params, step {step}")

def generate(prompt, max_tokens=80, temperature=0.9, top_k=50):
    tokens = enc.encode(prompt)
    x = torch.tensor([tokens], dtype=torch.long)
    with torch.no_grad():
        for _ in range(max_tokens):
            out = model(x[:, -512:])
            logits = out.logits[0, -1]
            # Clamp to prevent NaN/Inf
            logits = torch.clamp(logits, -100, 100)
            logits = logits / max(temperature, 0.1)
            # Replace any NaN with 0
            logits = torch.where(torch.isnan(logits), torch.zeros_like(logits), logits)
            logits = torch.where(torch.isinf(logits), torch.zeros_like(logits), logits)
            top = torch.topk(logits, min(top_k, logits.size(-1)))
            probs = torch.softmax(top.values, dim=-1)
            # Extra safety
            probs = torch.clamp(probs, min=1e-8)
            probs = probs / probs.sum()
            idx = torch.multinomial(probs, 1)
            next_token = top.indices[idx]
            x = torch.cat([x, next_token.unsqueeze(0)], dim=1)
    return enc.decode(x[0].tolist())

class Handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            prompt = body.get("prompt", "Hello")
            max_tokens = min(body.get("max_tokens", 80), 120)
            print(f"Prompt: {prompt[:60]}...")
            response = generate(prompt, max_tokens=max_tokens)
            result = {"response": response, "model": f"LOLM {params:,} params", "step": step, "prompt": prompt}
        except Exception as e:
            print(f"Error: {e}")
            result = {"response": prompt + " [generation error]", "model": f"LOLM {params:,} params", "step": step, "error": str(e)}
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(result).encode())

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ready", "model": f"LOLM {params:,} params", "step": step}).encode())

    def log_message(self, format, *args):
        pass

print("Chat server on http://localhost:8889")
HTTPServer(("", 8889), Handler).serve_forever()
