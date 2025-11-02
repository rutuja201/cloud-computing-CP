import time
import psutil
import platform
from flask import Flask, jsonify, Response, render_template_string
from prometheus_client import Gauge, generate_latest, CollectorRegistry, CONTENT_TYPE_LATEST

app = Flask(__name__)

# Prometheus metrics
registry = CollectorRegistry()
g_cpu = Gauge('container_cpu_percent', 'CPU percent', registry=registry)
g_mem = Gauge('container_memory_percent', 'Memory percent', registry=registry)
g_disk = Gauge('container_disk_percent', 'Disk percent', registry=registry)

# HTML template with clearly visible metric labels
DASHBOARD_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>System Monitoring Dashboard</title>
  <script src="https://cdn.plot.ly/plotly-2.24.1.min.js"></script>
  <style>
    body {
      font-family: Arial, sans-serif;
      margin: 30px;
      background-color: #fafafa;
    }
    h1 {
      font-size: 30px;
      color: #222;
    }
    #meta {
      margin-top: 5px;
      color: #666;
    }
    p.description {
      color: #444;
      margin-top: 10px;
      font-size: 16px;
      max-width: 850px;
    }
    .row {
      display: flex;
      justify-content: space-around;
      align-items: flex-start;
      flex-wrap: wrap;
      margin-top: 30px;
    }
    .card {
      width: 320px;
      text-align: center;
      background: white;
      border-radius: 10px;
      box-shadow: 0 0 10px rgba(0,0,0,0.05);
      padding: 15px;
    }
    h3.metric-label {
      margin-bottom: 10px;
      color: #333;
      font-weight: bold;
    }
    h3.section-title {
      margin-top: 40px;
      color: #222;
      border-bottom: 2px solid #ddd;
      padding-bottom: 5px;
    }
    pre {
      background: #f5f5f5;
      padding: 10px;
      border-radius: 8px;
      font-size: 14px;
    }
  </style>
</head>
<body>
  <h1>System Monitoring Dashboard</h1>
  <div id="meta"><strong>Host:</strong> {{ host }}</div>
  <p class="description">
    This dashboard shows <b>real-time system performance metrics</b> inside the running environment.  
    Each circular graph below represents <b>CPU</b>, <b>Memory</b>, and <b>Disk</b> usage in percentage, 
    while the sections below display <b>Network statistics</b> and <b>Top active processes</b>.
  </p>

  <!-- Row of labeled circular gauges -->
  <div class="row">
    <div class="card">
      <h3 class="metric-label">CPU Usage (%)</h3>
      <div id="cpu"></div>
    </div>
    <div class="card">
      <h3 class="metric-label">Memory Usage (%)</h3>
      <div id="mem"></div>
    </div>
    <div class="card">
      <h3 class="metric-label">Disk Usage (%)</h3>
      <div id="disk"></div>
    </div>
  </div>

  <h3 class="section-title">Network Statistics</h3>
  <pre id="netpre"></pre>

  <h3 class="section-title">Top Processes (by CPU)</h3>
  <div id="procs"></div>

<script>
async function fetchStats(){
  const res = await fetch('/api/stats');
  return res.json();
}

function makeGauge(container){
  const data = [{
    type: "pie",
    hole: .7,
    values: [1],
    marker: {colors:['#eee']},
    hoverinfo:'none',
    showlegend:false
  }];
  const layout = {
    margin:{t:30,b:30,l:30,r:30},
    height:260,
  };
  Plotly.newPlot(container, data, layout, {displayModeBar:false});
}

function updateGauge(container, value, max=100){
  const rate = Math.max(0, Math.min(100, value)) / max;
  const green = '#cfeead', yellow='#ffef93', red='#ff6b6b';
  const colored = [{
    values: [value, max-value],
    marker:{colors: [value>80?red:(value>50?yellow:green), '#eee']},
    hole: .7,
    type:'pie',
    textinfo:'none',
    hoverinfo:'none',
    showlegend:false
  }];
  const layout = { 
    margin:{t:40,b:20,l:20,r:20}, 
    height:260, 
    annotations:[{ text: String(value), showarrow:false, font:{size:30}, y:0.05 }] 
  };
  Plotly.react(container, colored, layout, {displayModeBar:false});
}

async function refresh(){
  try{
    const s = await fetchStats();
    updateGauge('cpu', Math.round(s.cpu));
    updateGauge('mem', Math.round(s.memory));
    updateGauge('disk', Math.round(s.disk));
    document.getElementById('netpre').textContent = JSON.stringify(s.net, null, 2);
    const procs = s.top_processes.map(p => 
      `<div>${p.pid} | ${p.name} | CPU: ${p.cpu}% | MEM: ${p.mem}%</div>`
    ).join('');
    document.getElementById('procs').innerHTML = procs;
  } catch(e){
    console.error(e);
  } finally {
    setTimeout(refresh, 2000);
  }
}

makeGauge('cpu');
makeGauge('mem');
makeGauge('disk');
refresh();
</script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(DASHBOARD_HTML, host=platform.node())

@app.route("/api/stats")
def api_stats():
    # ✅ Fix: Use interval=1 for accurate CPU usage
    cpu = psutil.cpu_percent(interval=1)
    
    vm = psutil.virtual_memory()

    # ✅ Fix: Adjust disk path for Windows or Linux
    try:
        disk = psutil.disk_usage('C:\\')  # Windows
    except Exception:
        disk = psutil.disk_usage('/')     # Linux / WSL fallback

    net_io = psutil.net_io_counters(pernic=False)._asdict()

    procs = []
    for p in psutil.process_iter(['pid','name','cpu_percent','memory_percent']):
        try:
            info = p.info
            procs.append({
                'pid': info['pid'],
                'name': info['name'] or '',
                'cpu': round(info['cpu_percent'],2),
                'mem': round(info['memory_percent'],2)
            })
        except Exception:
            continue
    procs = sorted(procs, key=lambda x: x['cpu'], reverse=True)[:8]

    # Update Prometheus gauges
    try:
        g_cpu.set(cpu)
        g_mem.set(vm.percent)
        g_disk.set(disk.percent)
    except Exception:
        pass

    return jsonify({
        'cpu': cpu,
        'memory': vm.percent,
        'disk': disk.percent,
        'net': net_io,
        'top_processes': procs,
        'timestamp': time.time()
    })

@app.route("/metrics")
def metrics():
    data = generate_latest(registry)
    return Response(data, mimetype=CONTENT_TYPE_LATEST)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
