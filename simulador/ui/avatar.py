"""Avaliador na tela: foto, bola falante ou juiz em vídeo, com a voz da banca (MP3) por cima.

Tudo roda num componente HTML: o áudio toca no navegador e a animação reage à amplitude.
Se o navegador bloquear o autoplay, aparece um botão para ouvir.
"""

from __future__ import annotations

import base64
import json

import streamlit as st
import streamlit.components.v1 as components

from .comum import asset_data_url

ALTURA = 380


def _html(formato: str, audio_mp3: bytes | None, autoplay: bool, videos: dict[str, str] | None, pensando: bool, ouvindo: bool) -> str:
    audio_src = f"data:audio/mpeg;base64,{base64.b64encode(audio_mp3).decode()}" if audio_mp3 else ""
    foto = asset_data_url("juiz-estatico.jpg", "image/jpeg")
    videos = videos or {}
    cfg = json.dumps(
        {
            "formato": formato,
            "audio": audio_src,
            "autoplay": bool(autoplay and audio_mp3),
            "videoOuvindo": videos.get("ouvindo", ""),
            "videoFalando": videos.get("falando", ""),
            "videoPensando": videos.get("pensando", "") or videos.get("ouvindo", ""),
            "pensando": pensando,
            "ouvindo": ouvindo,
        }
    )
    return f"""
<!doctype html><html><head><meta charset="utf-8"><style>
  html,body{{margin:0;background:transparent;font-family:system-ui,sans-serif}}
  .caixa{{position:relative;width:100%;height:{ALTURA - 8}px;border-radius:14px;overflow:hidden;background:#f3efe9;border:1px solid #ece6df}}
  .caixa img,.caixa video{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;transition:opacity .45s}}
  canvas{{position:absolute;inset:0;width:100%;height:100%}}
  .barras{{position:absolute;left:50%;bottom:14px;transform:translateX(-50%);display:none;gap:4px;align-items:flex-end;padding:8px 14px;border-radius:999px;background:rgba(255,255,255,.85)}}
  .barras span{{width:4px;height:4px;border-radius:2px;background:#d9581f;transition:height .06s}}
  .chip{{position:absolute;left:12px;bottom:12px;padding:6px 12px;border-radius:999px;background:rgba(255,255,255,.88);font-size:12px;color:#555}}
  .chip.dir{{left:auto;right:12px}}
  .botao{{position:absolute;inset:0;display:none;align-items:center;justify-content:center;background:rgba(255,255,255,.55);backdrop-filter:blur(3px)}}
  .botao button{{font:inherit;font-size:15px;padding:10px 18px;border-radius:10px;border:0;background:#d9581f;color:#fff;cursor:pointer}}
</style></head><body>
<div class="caixa" id="caixa">
  <img id="foto" src="{foto}" alt="Avaliador da banca" style="display:none">
  <video id="vOuvindo" muted loop playsinline preload="auto" style="display:none;opacity:1"></video>
  <video id="vFalando" muted loop playsinline preload="auto" style="display:none;opacity:0"></video>
  <canvas id="bola" style="display:none"></canvas>
  <div class="barras" id="barras"><span></span><span></span><span></span><span></span><span></span></div>
  <div class="chip" id="chipPensando" style="display:none">⏳ Analisando…</div>
  <div class="chip dir" id="chipOuvindo" style="display:none">🎙️ Ouvindo você</div>
  <div class="botao" id="botao"><button id="ouvir">▶ Ouvir o avaliador</button></div>
  <audio id="audio" preload="auto"></audio>
</div>
<script>
(function(){{
  const cfg = {cfg};
  const $ = id => document.getElementById(id);
  const audio = $('audio'), foto = $('foto'), bola = $('bola'), barras = $('barras'), botao = $('botao');
  const vO = $('vOuvindo'), vF = $('vFalando');
  $('chipPensando').style.display = cfg.pensando ? 'block' : 'none';
  $('chipOuvindo').style.display = (cfg.ouvindo && !cfg.audio) ? 'block' : 'none';

  if (cfg.formato === 'video' && cfg.videoOuvindo) {{
    vO.src = cfg.pensando ? cfg.videoPensando : cfg.videoOuvindo; vF.src = cfg.videoFalando;
    vO.style.display = vF.style.display = 'block';
    vO.play().catch(()=>{{}});
  }} else if (cfg.formato === 'bola') {{
    bola.style.display = 'block';
  }} else {{
    foto.style.display = 'block';
  }}

  let ctx, analyser, dados, raf, nivel = 0;
  function medir(){{
    if (analyser) {{ analyser.getByteTimeDomainData(dados); let s=0; for (const v of dados) s += (v-128)*(v-128); nivel = Math.min(1, Math.sqrt(s/dados.length)/128*3.2); }}
    desenhar(); raf = requestAnimationFrame(medir);
  }}
  function desenhar(){{
    if (cfg.formato === 'bola') {{
      const c = bola, g = c.getContext('2d'); const w = c.width = c.clientWidth, h = c.height = c.clientHeight;
      g.clearRect(0,0,w,h); const r = Math.min(w,h)*0.22*(1+nivel*0.35);
      const grad = g.createRadialGradient(w/2-r*0.3,h/2-r*0.3,r*0.1,w/2,h/2,r);
      grad.addColorStop(0,'#f28a4d'); grad.addColorStop(.6,'#d9581f'); grad.addColorStop(1,'rgba(217,88,31,.25)');
      g.shadowColor='rgba(217,88,31,'+(0.35+nivel*0.6)+')'; g.shadowBlur=20+nivel*60;
      g.fillStyle=grad; g.beginPath(); g.arc(w/2,h/2,r,0,Math.PI*2); g.fill();
    }} else if (cfg.formato === 'foto') {{
      const f=[0.6,1,0.75,1.1,0.5]; barras.querySelectorAll('span').forEach((s,i)=>{{ s.style.height = Math.max(4, nivel*26*f[i]) + 'px'; }});
    }}
  }}
  function ligarAnalise(){{
    if (ctx) return;
    try {{
      ctx = new (window.AudioContext||window.webkitAudioContext)();
      const src = ctx.createMediaElementSource(audio); analyser = ctx.createAnalyser(); analyser.fftSize = 512;
      src.connect(analyser); analyser.connect(ctx.destination); dados = new Uint8Array(analyser.frequencyBinCount);
    }} catch(e) {{}}
    if (!raf) medir();
  }}
  function falando(sim){{
    if (cfg.formato === 'video' && cfg.videoFalando) {{
      if (sim) {{ vF.currentTime = 0; vF.play().catch(()=>{{}}); vF.style.opacity = 1; vO.style.opacity = 0; }}
      else {{ vO.play().catch(()=>{{}}); vO.style.opacity = 1; vF.style.opacity = 0; }}
    }}
    if (cfg.formato === 'foto') barras.style.display = sim ? 'flex' : 'none';
    if (!sim) {{ nivel = 0; desenhar(); }}
  }}
  if (cfg.formato === 'bola') {{ desenhar(); }}
  if (cfg.audio) {{
    audio.src = cfg.audio;
    audio.addEventListener('play', ()=>{{ ligarAnalise(); if (ctx && ctx.state==='suspended') ctx.resume(); falando(true); botao.style.display='none'; }});
    audio.addEventListener('ended', ()=>falando(false));
    audio.addEventListener('pause', ()=>falando(false));
    $('ouvir').onclick = ()=>{{ audio.play().catch(()=>{{}}); }};
    if (cfg.autoplay) {{
      audio.play().catch(()=>{{ botao.style.display='flex'; }});
    }} else {{
      botao.style.display='flex'; $('ouvir').textContent = '▶ Ouvir novamente';
    }}
  }}
}})();
</script></body></html>
"""


def render_avatar(
    formato: str,
    audio_mp3: bytes | None = None,
    *,
    autoplay: bool = False,
    videos: dict[str, str] | None = None,
    pensando: bool = False,
    ouvindo: bool = False,
    chave: str | None = None,
) -> None:
    html = _html(formato, audio_mp3, autoplay, videos, pensando, ouvindo)
    if hasattr(st, "iframe"):  # Streamlit ≥ 1.63
        st.iframe(html, height=ALTURA)
    else:
        components.html(html, height=ALTURA)
