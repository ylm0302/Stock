/**
 * TradingAgents Dashboard — Vue 3 Application
 * Real-time SSE streaming, ECharts visualization, Markdown report rendering.
 *
 * NOTE: Uses Vue 3 Options API with CDN global build.
 * The template references methods via the Vue instance.
 */
(function () {
  const PROVIDERS = [
    { label: 'OpenAI',    value: 'openai',    shallow: 'gpt-5.4-mini',     deep: 'gpt-5.4' },
    { label: 'Google',    value: 'google',    shallow: 'gemini-1.5-mini',  deep: 'gemini-1.5-pro' },
    { label: 'Anthropic', value: 'anthropic', shallow: 'claude-3.5-mini',  deep: 'claude-4.1' },
    { label: 'DeepSeek',  value: 'deepseek',  shallow: 'deepseek-chat',    deep: 'deepseek-reasoner' },
    { label: 'Qwen',      value: 'qwen',      shallow: 'qwen-7b-mini',     deep: 'qwen-2.8b' },
    { label: 'GLM',       value: 'glm',       shallow: 'glm-6b-mini',      deep: 'glm-3.5' },
    { label: 'OpenRouter',value: 'openrouter',shallow: 'google/gemma-4o-mini', deep: 'google/gemma-4-26b-a4b' },
    { label: 'Ollama',    value: 'ollama',    shallow: 'llama-3-mini',     deep: 'llama-3' },
  ];

  const AGENT_LIST = [
    { name: 'Market Analyst',          team: 'Analyst' },
    { name: 'Sentiment Analyst',       team: 'Analyst' },
    { name: 'News Analyst',            team: 'Analyst' },
    { name: 'Fundamentals Analyst',    team: 'Analyst' },
    { name: 'Bull Researcher',         team: 'Research' },
    { name: 'Bear Researcher',         team: 'Research' },
    { name: 'Research Manager',        team: 'Research' },
    { name: 'Trader',                  team: 'Trading' },
    { name: 'Aggressive Risk Analyst', team: 'Risk' },
    { name: 'Neutral Risk Analyst',    team: 'Risk' },
    { name: 'Conservative Risk Analyst', team: 'Risk' },
    { name: 'Portfolio Manager',       team: 'PM' },
  ];

  var REPORT_TABS = [
    { key: 'market_report',          label: '市场分析' },
    { key: 'sentiment_report',       label: '情绪分析' },
    { key: 'news_report',            label: '新闻分析' },
    { key: 'fundamentals_report',    label: '基本面' },
    { key: 'investment_plan',        label: '研究决策' },
    { key: 'trader_investment_plan', label: '交易计划' },
    { key: 'final_trade_decision',   label: 'PM决策' },
  ];

  // ── Markdown ───────────────────────────────────────────────────────
  function safeMarkdown(text) {
    if (!text) return '';
    try {
      if (typeof marked !== 'undefined' && marked.parse) {
        return marked.parse(String(text), { breaks: true, gfm: true });
      }
    } catch (e) {
      console.warn('Markdown parse error:', e);
    }
    // Fallback
    return String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/\n/g, '<br>');
  }

  // ── Time helper ────────────────────────────────────────────────────
  function nowTime() {
    try {
      return new Date().toLocaleTimeString('zh-CN', { hour12: false });
    } catch (_) {
      var d = new Date();
      return [d.getHours(), d.getMinutes(), d.getSeconds()]
        .map(function(n) { return String(n).padStart(2,'0'); }).join(':');
    }
  }

  // ── SSE safe parse ─────────────────────────────────────────────────
  function safeParseEvent(e) {
    try {
      return JSON.parse(e.data);
    } catch (_) {
      return null;
    }
  }

  // ── Vue Application ────────────────────────────────────────────────
  var app = Vue.createApp({
    data: function () {
      return {
        serverOnline: true,
        statusInfo: {},

        providers: PROVIDERS,
        form: {
          ticker: '',
          analysis_date: new Date().toISOString().slice(0, 10),
          asset_type: 'stock',
          llm_provider: 'deepseek',
          shallow_thinker: 'deepseek-chat',
          deep_thinker: 'deepseek-reasoner',
          output_language: 'Chinese',
          research_depth: 1,
          checkpoint: false,
          backend_url: '',
          api_key: '',
        },

        // Profiles state
        profiles: [],
        activeProfileName: '',
        profileDirty: false,
        showApiKey: false,

        running: false,
        currentJobId: null,
        eventSource: null,

        // Each agent object: { name, team, status }
        agents: [],
        // Map of agentName -> status string (kept in sync with agents array)
        agentStatusMap: {},

        reportTabs: REPORT_TABS,
        activeTab: 'market_report',
        reportSections: {},

        history: [],
        logs: [],

        chartData: null,
        chartLoading: false,
        chartInstance: null,
      };
    },

    computed: {
      completedCount: function () {
        return Object.values(this.agentStatusMap).filter(function(s) { return s === 'completed'; }).length;
      },
      progressPercent: function () {
        var total = Object.keys(this.agentStatusMap).length || 1;
        return Math.round((this.completedCount / total) * 100);
      },
      currentTabLabel: function () {
        var tab = this.reportTabs.find(function(t) { return t.key === this.activeTab; }, this);
        return tab ? tab.label : '';
      },
      activeProfileConfig: function () {
        var p = this.profiles.find(function (x) { return x.name === this.activeProfileName; }, this);
        return p ? (p.config || {}) : {};
      },
      maskedApiKey: function () {
        var key = this.activeProfileConfig.api_key || '';
        if (!key) return '—';
        if (key.indexOf('•') !== -1) return key;
        if (key.length < 7) return '•••';
        return key.slice(0, 3) + '••••' + key.slice(-4);
      },
    },

    methods: {
      // ── Status helpers ──────────────────────────────────────────
      agentStatusBg: function (status) {
        var map = {
          pending:   'bg-slate-800 text-slate-500',
          running:   'bg-blue-900/30 text-blue-300 border border-blue-500/30',
          completed: 'bg-emerald-900/20 text-emerald-300',
        };
        return map[status] || 'bg-slate-800 text-slate-500';
      },

      agentStatusDot: function (status) {
        var map = {
          pending:   'bg-slate-600',
          running:   'bg-blue-400 animate-pulse',
          completed: 'bg-emerald-400',
        };
        return map[status] || 'bg-slate-600';
      },

      statusLabel: function (status) {
        var map = {
          pending:   '等待',
          running:   '执行中',
          completed: '完成',
        };
        return map[status] || status || '?';
      },

      logLevelClass: function (level) {
        var map = {
          error: 'text-red-400',
          warn:  'text-yellow-400',
          info:  'text-slate-400',
        };
        return map[level] || 'text-slate-400';
      },

      renderMarkdown: function (text) {
        return safeMarkdown(text);
      },

      // ── Form ────────────────────────────────────────────────────
      onProviderChange: function () {
        var self = this;
        var p = self.providers.find(function(x) { return x.value === self.form.llm_provider; });
        if (p) {
          self.form.shallow_thinker = p.shallow;
          self.form.deep_thinker = p.deep;
        }
        self.checkProfileDirty();
      },

      // ── Profiles ────────────────────────────────────────────────
      profileEmoji: function (name) {
        if (/家/.test(name)) return '🏠';
        if (/公司|工作/.test(name)) return '🏢';
        if (/本地|ollama/i.test(name)) return '🔬';
        return '⭐';
      },

      loadProfiles: function () {
        var self = this;
        fetch('/api/profiles')
          .then(function (r) { return r.json(); })
          .then(function (data) {
            self.profiles = data.profiles || [];
            var active = data.active || (self.profiles[0] && self.profiles[0].name) || '';
            self.activeProfileName = active;
            self.applyProfileToForm();
          })
          .catch(function (e) { self.addLog('加载配置方案失败: ' + e.message, 'error'); });
      },

      applyProfileToForm: function () {
        var cfg = this.activeProfileConfig;
        if (!cfg || !this.activeProfileName) return;
        if (cfg.llm_provider) this.form.llm_provider = cfg.llm_provider;
        if (cfg.backend_url !== undefined) this.form.backend_url = cfg.backend_url || '';
        if (cfg.api_key && cfg.api_key.indexOf('•') === -1) {
          this.form.api_key = cfg.api_key;
        } else {
          this.form.api_key = '';
        }
        if (cfg.shallow_thinker) this.form.shallow_thinker = cfg.shallow_thinker;
        if (cfg.deep_thinker) this.form.deep_thinker = cfg.deep_thinker;
        if (cfg.output_language) this.form.output_language = cfg.output_language;
        if (cfg.research_depth !== undefined) this.form.research_depth = cfg.research_depth;
        if (cfg.checkpoint !== undefined) this.form.checkpoint = cfg.checkpoint;
        if (cfg.asset_type) this.form.asset_type = cfg.asset_type;
        this.profileDirty = false;
      },

      currentFormAsConfig: function () {
        return {
          llm_provider: this.form.llm_provider,
          backend_url: this.form.backend_url,
          api_key: this.form.api_key,
          shallow_thinker: this.form.shallow_thinker,
          deep_thinker: this.form.deep_thinker,
          output_language: this.form.output_language,
          research_depth: this.form.research_depth,
          checkpoint: this.form.checkpoint,
          asset_type: this.form.asset_type,
        };
      },

      saveProfile: function () {
        var self = this;
        if (!self.activeProfileName) {
          self.addLog('请先选择一个方案或使用「另存为」', 'warn');
          return;
        }
        fetch('/api/profiles', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: self.activeProfileName, config: self.currentFormAsConfig() }),
        })
          .then(function (r) {
            if (!r.ok) return r.text().then(function (t) { throw new Error(t); });
            return r.json();
          })
          .then(function () {
            self.addLog('已保存方案: ' + self.activeProfileName);
            self.profileDirty = false;
            self.loadProfiles();
          })
          .catch(function (e) { self.addLog('保存方案失败: ' + e.message, 'error'); });
      },

      saveAsProfile: function () {
        var self = this;
        var name = prompt('输入新方案名称:');
        if (!name || !name.trim()) return;
        name = name.trim();
        var exists = self.profiles.some(function (p) { return p.name === name; });
        if (exists && !confirm('方案「' + name + '」已存在，是否覆盖？')) return;

        fetch('/api/profiles', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: name, config: self.currentFormAsConfig() }),
        })
          .then(function (r) {
            if (!r.ok) return r.text().then(function (t) { throw new Error(t); });
            return r.json();
          })
          .then(function () {
            self.activeProfileName = name;
            self.addLog('已创建方案: ' + name);
            self.profileDirty = false;
            self.loadProfiles();
          })
          .catch(function (e) { self.addLog('创建方案失败: ' + e.message, 'error'); });
      },

      deleteProfile: function () {
        var self = this;
        if (!self.activeProfileName) return;
        if (!confirm('确定删除方案「' + self.activeProfileName + '」？此操作不可恢复。')) return;

        fetch('/api/profiles?name=' + encodeURIComponent(self.activeProfileName), {
          method: 'DELETE',
        })
          .then(function (r) {
            if (!r.ok) return r.text().then(function (t) { throw new Error(t); });
            return r.json();
          })
          .then(function (data) {
            self.addLog('已删除方案: ' + self.activeProfileName);
            self.activeProfileName = data.active || '';
            self.loadProfiles();
          })
          .catch(function (e) { self.addLog('删除方案失败: ' + e.message, 'error'); });
      },

      onProfileSwitch: function () {
        var self = this;
        if (self.profileDirty) {
          if (!confirm('当前方案有未保存的改动，切换将丢弃。是否继续？')) {
            self.$nextTick(function () {
              self.activeProfileName = self.profiles[0] ? self.profiles[0].name : '';
            });
            return;
          }
        }
        fetch('/api/profiles/activate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: self.activeProfileName }),
        }).catch(function () { /* non-critical */ });
        self.applyProfileToForm();
      },

      checkProfileDirty: function () {
        var cfg = this.activeProfileConfig;
        if (!cfg || !this.activeProfileName) {
          this.profileDirty = false;
          return;
        }
        var cur = this.currentFormAsConfig();
        var dirty = false;
        ['llm_provider', 'backend_url', 'shallow_thinker', 'deep_thinker',
         'output_language', 'research_depth', 'checkpoint', 'asset_type'].forEach(function (k) {
          if (cfg[k] !== undefined && cfg[k] !== cur[k]) dirty = true;
        });
        if (cur.api_key && !cfg.api_key) dirty = true;
        this.profileDirty = dirty;
      },

      // ── Logging ─────────────────────────────────────────────────
      addLog: function (message, level) {
        level = level || 'info';
        this.logs.push({ time: nowTime(), message: String(message), level: level });
        // Keep max 500 log entries
        if (this.logs.length > 500) this.logs.splice(0, this.logs.length - 500);
        // Auto-scroll on next tick
        var self = this;
        this.$nextTick(function () {
          var el = self.$refs.logContainer;
          if (el) el.scrollTop = el.scrollHeight;
        });
      },

      // ── Agent state ─────────────────────────────────────────────
      initAgents: function () {
        var self = this;
        self.agents = AGENT_LIST.map(function (a) {
          return { name: a.name, team: a.team, status: 'pending' };
        });
        self.agentStatusMap = {};
        self.agents.forEach(function (a) {
          self.agentStatusMap[a.name] = 'pending';
        });
      },

      setAgentStatus: function (agentName, status) {
        // Update the agent object in the agents array (for template reactivity)
        var agent = this.agents.find(function(a) { return a.name === agentName; });
        if (agent) {
          agent.status = status;
        }
        // Also update the map
        this.agentStatusMap[agentName] = status;
        // Force Vue to detect the change by replacing the map reference
        this.agentStatusMap = Object.assign({}, this.agentStatusMap);
      },

      // ── History ─────────────────────────────────────────────────
      loadHistory: function () {
        var self = this;
        fetch('/api/tickers')
          .then(function(r) { return r.json(); })
          .then(function(data) { self.history = data.tickers || []; })
          .catch(function(e) { self.addLog('加载历史失败: ' + e.message, 'error'); });
      },

      loadReport: function (ticker, date) {
        var self = this;
        self.addLog('加载报告 ' + ticker + ' / ' + date + ' ...');
        fetch('/api/report?ticker=' + encodeURIComponent(ticker) + '&date=' + encodeURIComponent(date))
          .then(function(r) {
            if (!r.ok) return r.text().then(function(t) { throw new Error(t); });
            return r.json();
          })
          .then(function(data) {
            // Reset and populate report sections
            var sections = {};
            if (data._sections && data._sections.length) {
              data._sections.forEach(function(s) { sections[s.key] = s.content; });
            } else {
              // Fallback: extract known keys
              REPORT_TABS.forEach(function(tab) {
                if (data[tab.key]) sections[tab.key] = data[tab.key];
              });
            }
            self.reportSections = sections;

            // Switch to first available tab
            for (var i = 0; i < REPORT_TABS.length; i++) {
              if (sections[REPORT_TABS[i].key]) {
                self.activeTab = REPORT_TABS[i].key;
                break;
              }
            }

            self.loadChart(ticker);
            self.addLog('已加载报告 ' + ticker + ' / ' + date);
          })
          .catch(function(e) {
            self.addLog('加载报告失败: ' + e.message, 'error');
          });
      },

      // ── Charts ──────────────────────────────────────────────────
      loadChart: function (ticker) {
        var self = this;
        self.chartLoading = true;
        fetch('/api/chart?ticker=' + encodeURIComponent(ticker))
          .then(function(r) {
            if (!r.ok) return r.text().then(function(t) { throw new Error(t); });
            return r.json();
          })
          .then(function(data) {
            self.chartData = data;
            self.$nextTick(function() { self.renderChart(); });
          })
          .catch(function(e) {
            self.addLog('加载图表失败: ' + e.message, 'warn');
            self.chartData = null;
          })
          .finally(function() {
            self.chartLoading = false;
          });
      },

      renderChart: function () {
        if (!this.chartData || !this.chartData.ohlc) return;
        var container = document.getElementById('chart-container');
        if (!container) return;

        try {
          if (this.chartInstance) this.chartInstance.dispose();
          this.chartInstance = echarts.init(container, 'dark');

          var ohlcValues = this.chartData.ohlc.map(function(d) {
            return [d[1], d[2], d[3], d[4]]; // [open, close, low, high]
          });

          var option = {
            backgroundColor: 'transparent',
            grid: { left: 8, right: 16, top: 8, bottom: 24 },
            xAxis: {
              type: 'category',
              data: this.chartData.ohlc.map(function(d) { return d[0]; }),
              axisLine: { lineStyle: { color: '#475569' } },
              axisLabel: { color: '#64748b', fontSize: 9, formatter: function(v) { return v.slice(5); } },
              show: false,
            },
            yAxis: {
              type: 'value',
              scale: true,
              axisLine: { show: false },
              axisLabel: { color: '#64748b', fontSize: 9 },
              splitLine: { lineStyle: { color: '#1e293b' } },
            },
            tooltip: {
              trigger: 'axis',
              axisPointer: { type: 'cross' },
              backgroundColor: '#1e293b',
              borderColor: '#334155',
              textStyle: { color: '#e2e8f0', fontSize: 11 },
            },
            series: [{
              type: 'candlestick',
              data: ohlcValues,
              itemStyle: {
                color: '#22c55e',
                color0: '#ef4444',
                borderColor: '#22c55e',
                borderColor0: '#ef4444',
              },
            }],
          };

          this.chartInstance.setOption(option);
        } catch (e) {
          console.warn('Chart render error:', e);
        }
      },

      // ── SSE Stream ──────────────────────────────────────────────
      connectSSE: function (jobId) {
        var self = this;
        self.disconnectSSE();

        var url = '/api/stream/' + jobId;
        self.addLog('连接实时流: ' + jobId.slice(0, 8) + '...');

        try {
          self.eventSource = new EventSource(url);
        } catch (e) {
          self.addLog('SSE 连接失败: ' + e.message, 'error');
          self.running = false;
          return;
        }

        // ── agent_start ──
        self.eventSource.addEventListener('agent_start', function(e) {
          var data = safeParseEvent(e);
          if (!data || !data.agent) return;
          self.setAgentStatus(data.agent, 'running');
          self.addLog(data.agent + ' 开始工作');
        });

        // ── agent_done ──
        self.eventSource.addEventListener('agent_done', function(e) {
          var data = safeParseEvent(e);
          if (!data || !data.agent) return;
          self.setAgentStatus(data.agent, 'completed');
          self.addLog(data.agent + ' 完成');
        });

        // ── report_section ──
        self.eventSource.addEventListener('report_section', function(e) {
          var data = safeParseEvent(e);
          if (!data || !data.key) return;
          // Create new object to trigger Vue reactivity
          var newSections = Object.assign({}, self.reportSections);
          newSections[data.key] = data.content;
          self.reportSections = newSections;
          self.activeTab = data.key;
          self.addLog('报告更新: ' + (data.label || data.key));
        });

        // ── final_decision ──
        self.eventSource.addEventListener('final_decision', function(e) {
          var data = safeParseEvent(e);
          if (!data) return;
          var newSections = Object.assign({}, self.reportSections);
          newSections['final_trade_decision'] = data.decision || '';
          self.reportSections = newSections;
          self.activeTab = 'final_trade_decision';
          self.addLog('最终决策已生成');
        });

        // ── log ──
        self.eventSource.addEventListener('log', function(e) {
          var data = safeParseEvent(e);
          if (!data) return;
          self.addLog(data.message || '', data.level || 'info');
        });

        // ── done ──
        self.eventSource.addEventListener('done', function(e) {
          var data = safeParseEvent(e) || {};
          self.addLog('分析完成', 'info');
          self.running = false;
          self.disconnectSSE();
          self.loadHistory();
          if (data.ticker) self.loadChart(data.ticker);
        });

        // ── error ──
        self.eventSource.addEventListener('error', function(e) {
          var data = safeParseEvent(e);
          self.addLog('错误: ' + (data && data.message ? data.message : '未知错误'), 'error');
          self.running = false;
          self.disconnectSSE();
        });

        // ── stream_end ──
        self.eventSource.addEventListener('stream_end', function() {
          self.disconnectSSE();
        });

        // ── connection error ──
        self.eventSource.onerror = function() {
          self.addLog('SSE 连接断开', 'warn');
          if (self.running) {
            // Don't set running=false on transient errors;
            // the server will send 'done' or 'error' events when ready.
            // Only mark as stopped if EventSource is CLOSED.
            if (self.eventSource && self.eventSource.readyState === EventSource.CLOSED) {
              self.addLog('流已关闭', 'warn');
              self.running = false;
              self.disconnectSSE();
            }
          }
        };
      },

      disconnectSSE: function () {
        if (this.eventSource) {
          this.eventSource.close();
          this.eventSource = null;
        }
      },

      // ── Start analysis ──────────────────────────────────────────
      startAnalysis: function () {
        var self = this;

        if (!self.form.ticker || !self.form.ticker.trim()) {
          self.addLog('请输入标的代码', 'warn');
          return;
        }
        if (!self.form.analysis_date) {
          self.addLog('请选择分析日期', 'warn');
          return;
        }

        // Reset state
        self.running = true;
        self.reportSections = {};
        self.activeTab = 'market_report';
        self.initAgents();
        self.chartData = null;
        self.addLog('开始分析 ' + self.form.ticker.trim().toUpperCase() + ' (' + self.form.analysis_date + ')');

        var payload = {
          ticker: self.form.ticker.trim().toUpperCase(),
          analysis_date: self.form.analysis_date,
          asset_type: self.form.asset_type || 'stock',
          selected_analysts: ['market', 'social', 'news', 'fundamentals'],
          llm_provider: self.form.llm_provider || 'deepseek',
          backend_url: self.form.backend_url || '',
          shallow_thinker: (self.form.shallow_thinker || '').trim(),
          deep_thinker: (self.form.deep_thinker || '').trim(),
          output_language: self.form.output_language || 'Chinese',
          research_depth: self.form.research_depth || 1,
          checkpoint: !!self.form.checkpoint,
          profile: self.activeProfileName || null,
        };

        fetch('/api/run', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        })
          .then(function(r) {
            if (!r.ok) return r.text().then(function(t) { throw new Error(t); });
            return r.json();
          })
          .then(function(data) {
            self.currentJobId = data.job_id;
            self.addLog('任务已创建: ' + data.job_id.slice(0, 8) + '...');
            self.connectSSE(data.job_id);
          })
          .catch(function(e) {
            self.addLog('提交分析失败: ' + e.message, 'error');
            self.running = false;
          });
      },
    },

    // ── Lifecycle ─────────────────────────────────────────────────
    mounted: function () {
      var self = this;
      self.loadHistory();
      self.loadProfiles();

      // Initial health check
      fetch('/api/status')
        .then(function(r) { return r.json(); })
        .then(function(d) { self.statusInfo = d; self.serverOnline = true; })
        .catch(function() { self.serverOnline = false; });

      // Periodic health check
      self._healthTimer = setInterval(function() {
        fetch('/api/status')
          .then(function(r) { return r.json(); })
          .then(function(d) { self.statusInfo = d; self.serverOnline = true; })
          .catch(function() { self.serverOnline = false; });
      }, 30000);

      // Handle window resize for chart
      self._resizeHandler = function() {
        if (self.chartInstance) {
          try { self.chartInstance.resize(); } catch(_) {}
        }
      };
      window.addEventListener('resize', self._resizeHandler);
    },

    beforeUnmount: function () {
      this.disconnectSSE();
      if (this._healthTimer) clearInterval(this._healthTimer);
      if (this._resizeHandler) window.removeEventListener('resize', this._resizeHandler);
      if (this.chartInstance) {
        try { this.chartInstance.dispose(); } catch(_) {}
        this.chartInstance = null;
      }
    },
  });

  app.mount('#app');
})();