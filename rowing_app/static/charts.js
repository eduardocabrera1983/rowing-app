/* ── Laat Lopen — Apache ECharts dashboard renderer ──
 * Reads the JSON payload embedded by the server (#chart-data) and renders
 * every chart client-side with the brand palette, matching the active theme.
 */
(function () {
    'use strict';

    var dataEl = document.getElementById('chart-data');
    if (!dataEl || !window.echarts) return;
    var DATA = JSON.parse(dataEl.textContent);

    var PALETTE = {
        indigo: '#6379F2',
        indigoMuted: '#606EBF',
        indigoLight: '#9AA6F8',
        sky: '#79BAF2',
        skyLight: '#A9D4F7',
        green: '#11BF7F',
        mint: '#5BD9A8',
        violet: '#9B6BF2',
        amber: '#F2B33D',
        red: '#ef4444'
    };

    var CLUSTER_COLORS = {
        'Sprint': PALETTE.amber,
        '5K Steady-State': PALETTE.green,
        'Mid-Distance (5-10K)': PALETTE.indigo,
        '10K Steady-State': PALETTE.sky,
        'Endurance 10K+': PALETTE.violet
    };
    var CLUSTER_COLORS_HI = {
        'Sprint': '#F7CE7E',
        '5K Steady-State': '#7FE6C0',
        'Mid-Distance (5-10K)': '#8E9DF6',
        '10K Steady-State': '#C2E0FA',
        'Endurance 10K+': '#BFA3F7'
    };
    var FALLBACK_COLORS = [PALETTE.sky, PALETTE.green, PALETTE.indigo, PALETTE.violet, PALETTE.amber];

    function clusterColor(label, idx) {
        if (CLUSTER_COLORS[label]) return CLUSTER_COLORS[label];
        var base = label.replace(' (High Intensity)', '');
        if (CLUSTER_COLORS_HI[base]) return CLUSTER_COLORS_HI[base];
        return FALLBACK_COLORS[idx % FALLBACK_COLORS.length];
    }

    function isDark() {
        return document.documentElement.getAttribute('data-theme') !== 'light';
    }

    function themeColors() {
        return isDark() ? {
            text: '#e3e8f0', textSoft: '#b9c2d0', grid: '#2c3745', axis: '#3a4553',
            tooltipBg: '#222b38', emptyCell: '#1f2630', border: '#2c3745'
        } : {
            text: '#333333', textSoft: '#555555', grid: '#ebedf0', axis: '#cccccc',
            tooltipBg: '#ffffff', emptyCell: '#ebedf0', border: '#d0ddf0'
        };
    }

    function fmtPace(sec) {
        if (sec == null) return '–';
        var m = Math.floor(sec / 60);
        var s = sec - m * 60;
        var ss = s.toFixed(1);
        if (s < 10) ss = '0' + ss;
        return m + ':' + ss;
    }

    function fmtPaceTick(sec) {
        var m = Math.floor(sec / 60);
        var s = Math.round(sec - m * 60);
        return m + ':' + (s < 10 ? '0' : '') + s;
    }

    function baseOption(c) {
        return {
            animationDuration: 500,
            textStyle: { color: c.text, fontFamily: 'inherit' },
            tooltip: {
                backgroundColor: c.tooltipBg,
                borderColor: c.border,
                textStyle: { color: c.text }
            }
        };
    }

    function axisCommon(c) {
        return {
            axisLine: { lineStyle: { color: c.axis } },
            axisLabel: { color: c.textSoft },
            splitLine: { lineStyle: { color: c.grid } }
        };
    }

    var registry = [];  // {el, build} — so we can rebuild on theme change

    function register(id, build) {
        var el = document.getElementById(id);
        if (!el) return;
        registry.push({ el: el, build: build });
    }

    function renderAll() {
        registry.forEach(function (r) {
            if (r.chart) { r.chart.dispose(); }
            r.chart = echarts.init(r.el, null, { renderer: 'canvas' });
            r.chart.setOption(r.build(themeColors()));
        });
    }

    // ── Stroke-level detail: pace + stroke rate (+ HR), synced with dataZoom ──
    if (DATA.stroke_detail) {
        register('ec-stroke', function (c) {
            var d = DATA.stroke_detail;
            var hasHr = d.has_hr && d.hrs.length;
            var grids = [
                { left: 70, right: 24, top: 40, height: '32%' },
                { left: 70, right: 24, top: hasHr ? '48%' : '58%', height: hasHr ? '18%' : '28%' }
            ];
            if (hasHr) grids.push({ left: 70, right: 24, top: '72%', height: '16%' });

            var paces = d.paces_smooth.filter(function (v) { return v != null; });
            var pMin = Math.min.apply(null, paces), pMax = Math.max.apply(null, paces);

            function series(xi, data, name, color, width, opacity) {
                return {
                    name: name, type: 'line', xAxisIndex: xi, yAxisIndex: xi,
                    data: d.times_min.map(function (t, i) { return [t, data[i]]; }),
                    showSymbol: false, symbol: 'circle',
                    lineStyle: { color: color, width: width, opacity: opacity == null ? 1 : opacity },
                    itemStyle: { color: color },
                    connectNulls: false, large: true
                };
            }

            var xAxes = grids.map(function (_, i) {
                return {
                    type: 'value', gridIndex: i, min: 0, max: 'dataMax',
                    axisLabel: i === grids.length - 1 ? { color: c.textSoft, formatter: '{value} min' } : { show: false },
                    axisLine: { lineStyle: { color: c.axis } },
                    splitLine: { lineStyle: { color: c.grid } }
                };
            });

            var yAxes = [
                Object.assign({ type: 'value', gridIndex: 0, inverse: true, name: 'Pace /500m',
                    nameTextStyle: { color: c.textSoft },
                    min: Math.floor((pMin - 6) / 5) * 5, max: Math.ceil((pMax + 6) / 5) * 5,
                    axisLabel: { color: c.textSoft, formatter: fmtPaceTick } }, {
                    axisLine: { lineStyle: { color: c.axis } }, splitLine: { lineStyle: { color: c.grid } } }),
                Object.assign({ type: 'value', gridIndex: 1, name: 'spm', scale: true,
                    nameTextStyle: { color: c.textSoft } }, axisCommon(c))
            ];
            if (hasHr) {
                yAxes.push(Object.assign({ type: 'value', gridIndex: 2, name: 'bpm', scale: true,
                    nameTextStyle: { color: c.textSoft } }, axisCommon(c)));
            }

            var ser = [
                series(0, d.paces_raw, 'Pace (per stroke)', PALETTE.indigo, 1, 0.25),
                series(0, d.paces_smooth, 'Pace', PALETTE.indigo, 2.5),
                series(1, d.spms, 'Stroke Rate', PALETTE.green, 2)
            ];
            if (hasHr) ser.push(series(2, d.hrs, 'Heart Rate', PALETTE.red, 2));

            return Object.assign(baseOption(c), {
                axisPointer: { link: [{ xAxisIndex: 'all' }] },
                tooltip: Object.assign(baseOption(c).tooltip, {
                    trigger: 'axis',
                    valueFormatter: null,
                    formatter: function (params) {
                        var lines = [params[0].value[0].toFixed(2) + ' min'];
                        params.forEach(function (p) {
                            if (p.seriesName === 'Pace (per stroke)') return;
                            var v = p.value[1];
                            if (v == null) return;
                            if (p.seriesName === 'Pace') v = fmtPace(v) + ' /500m';
                            else if (p.seriesName === 'Stroke Rate') v = v + ' spm';
                            else if (p.seriesName === 'Heart Rate') v = v + ' bpm';
                            lines.push(p.marker + ' ' + p.seriesName + ': <b>' + v + '</b>');
                        });
                        return lines.join('<br>');
                    }
                }),
                grid: grids,
                xAxis: xAxes,
                yAxis: yAxes,
                dataZoom: [
                    { type: 'inside', xAxisIndex: grids.map(function (_, i) { return i; }) },
                    { type: 'slider', xAxisIndex: grids.map(function (_, i) { return i; }),
                      bottom: 6, height: 18, borderColor: c.border,
                      fillerColor: 'rgba(99,121,242,0.15)', handleStyle: { color: PALETTE.indigo } }
                ],
                series: ser
            });
        });
    }

    // ── Monthly / weekly volume bars ──
    function barChart(id, key, color) {
        if (!DATA[key]) return;
        register(id, function (c) {
            var d = DATA[key];
            return Object.assign(baseOption(c), {
                title: { text: key === 'monthly_distance' ? 'Monthly Distance (km)' : 'Weekly Distance (km)',
                         left: 'center', textStyle: { color: c.text, fontSize: 15 } },
                tooltip: Object.assign(baseOption(c).tooltip, {
                    trigger: 'axis',
                    formatter: function (ps) { return ps[0].name + ': <b>' + ps[0].value + ' km</b>'; }
                }),
                grid: { left: 56, right: 20, top: 48, bottom: 56 },
                xAxis: Object.assign({ type: 'category', data: d.labels,
                    axisLabel: { color: c.textSoft, rotate: d.labels.length > 24 ? 60 : 0 } }, {
                    axisLine: { lineStyle: { color: c.axis } } }),
                yAxis: Object.assign({ type: 'value' }, axisCommon(c)),
                series: [{
                    type: 'bar', data: d.km, itemStyle: { color: color, borderRadius: [3, 3, 0, 0] },
                    emphasis: { itemStyle: { color: PALETTE.indigoLight } }
                }]
            });
        });
    }
    barChart('ec-monthly', 'monthly_distance', PALETTE.indigo);
    barChart('ec-weekly', 'weekly_distance', PALETTE.sky);

    // ── GitHub-style training calendar heatmap (one row per year) ──
    if (DATA.heatmap) {
        (function () {
            var d = DATA.heatmap;
            var y0 = parseInt(d.range[0].slice(0, 4), 10);
            var y1 = parseInt(d.range[1].slice(0, 4), 10);
            var years = [];
            for (var y = y0; y <= y1; y++) years.push(y);

            var el = document.getElementById('ec-heatmap');
            if (el) el.style.height = (years.length * 120 + 60) + 'px';

            register('ec-heatmap', function (c) {
                var calendars = years.map(function (y, i) {
                    var range;
                    if (years.length === 1) range = [d.range[0], d.range[1]];
                    else if (y === y0) range = [d.range[0], y + '-12-31'];
                    else if (y === y1) range = [y + '-01-01', d.range[1]];
                    else range = String(y);
                    return {
                        range: range,
                        cellSize: ['auto', 13],
                        left: 60, right: 10, top: 25 + i * 120, height: 95,
                        splitLine: { show: false },
                        itemStyle: { color: c.emptyCell, borderColor: isDark() ? '#11151c' : '#f5f6fa', borderWidth: 2.5 },
                        dayLabel: { color: c.textSoft, firstDay: 1, fontSize: 10 },
                        monthLabel: { color: c.textSoft, fontSize: 11 },
                        yearLabel: { color: c.text, fontSize: 13, margin: 28 }
                    };
                });
                var series = years.map(function (y, i) {
                    return {
                        type: 'heatmap', coordinateSystem: 'calendar', calendarIndex: i,
                        data: d.data.filter(function (row) { return row[0].slice(0, 4) === String(y); }),
                        itemStyle: { borderRadius: 2 }
                    };
                });
                return Object.assign(baseOption(c), {
                    tooltip: Object.assign(baseOption(c).tooltip, {
                        formatter: function (p) {
                            return p.value[0] + '<br>Distance: <b>' + p.value[1].toLocaleString() + ' m</b>';
                        }
                    }),
                    visualMap: {
                        min: 0, max: d.max, type: 'continuous', orient: 'horizontal',
                        left: 'center', bottom: 0, text: ['more', 'less'],
                        textStyle: { color: c.textSoft }, itemHeight: 90,
                        // Brand ramp: violet (light days) -> sky -> green -> amber (biggest days)
                        inRange: { color: [PALETTE.violet, PALETTE.sky, PALETTE.green, PALETTE.amber] }
                    },
                    calendar: calendars,
                    series: series
                });
            });
        })();
    }

    // ── Pace trend regression ──
    if (DATA.regression) {
        register('ec-regression', function (c) {
            var d = DATA.regression;
            var sel = document.getElementById('reg-model-select');
            var mode = sel ? sel.value : 'both';

            // Dot colour matches the brand bands; the fastest 5% get the amber
            // "record" accent so standout days pop.
            var sorted = d.paces.slice().sort(function (a, b) { return a - b; });
            var p05 = sorted[Math.max(0, Math.floor(sorted.length * 0.05) - 1)] || sorted[0];
            function dotColor(v) {
                if (v <= p05) return PALETTE.amber;
                return v <= 160 ? PALETTE.green : (v <= 172 ? PALETTE.sky : PALETTE.violet);
            }

            function line(name, ys, color, dash, width, show) {
                return {
                    name: name, type: 'line',
                    data: d.dates.map(function (dt, i) { return [dt, ys[i]]; }),
                    showSymbol: false, connectNulls: true,
                    lineStyle: { color: color, width: width, type: dash ? 'dashed' : 'solid',
                                 opacity: show ? 1 : 0 },
                    itemStyle: { color: color },
                    tooltip: { show: show },
                    silent: !show, z: 3
                };
            }

            return Object.assign(baseOption(c), {
                title: { text: 'Pace Trend — Linear & Polynomial Regression', left: 'center',
                         textStyle: { color: c.text, fontSize: 15 } },
                legend: {
                    bottom: 0, textStyle: { color: c.textSoft },
                    data: ['Actual Pace', 'Linear', 'Polynomial', '10-workout Rolling Avg']
                },
                tooltip: Object.assign(baseOption(c).tooltip, {
                    trigger: 'item',
                    formatter: function (p) {
                        var v = p.value[1];
                        return p.value[0] + '<br>' + p.marker + ' ' + p.seriesName + ': <b>' + fmtPace(v) + ' /500m</b>';
                    }
                }),
                grid: { left: 64, right: 24, top: 48, bottom: 64 },
                xAxis: Object.assign({ type: 'time' }, {
                    axisLine: { lineStyle: { color: c.axis } },
                    axisLabel: { color: c.textSoft },
                    splitLine: { show: false } }),
                yAxis: Object.assign({ type: 'value', inverse: true, scale: true,
                    name: 'Pace /500m', nameTextStyle: { color: c.textSoft },
                    axisLabel: { color: c.textSoft, formatter: fmtPaceTick } }, {
                    axisLine: { lineStyle: { color: c.axis } },
                    splitLine: { lineStyle: { color: c.grid } } }),
                series: [
                    {
                        name: 'Actual Pace', type: 'scatter',
                        data: d.dates.map(function (dt, i) { return [dt, d.paces[i]]; }),
                        symbolSize: 9,
                        itemStyle: {
                            color: function (p) { return dotColor(p.value[1]); },
                            opacity: 0.85
                        },
                        z: 2
                    },
                    line('Linear', d.trend_y, PALETTE.indigo, true, 2, mode !== 'poly'),
                    line('Polynomial', d.poly_y, PALETTE.indigoMuted, false, 2.5, mode !== 'linear'),
                    line('10-workout Rolling Avg', d.rolling_avg, PALETTE.indigoLight, false, 1.6, true)
                ]
            });
        });

        // Model selector re-renders the regression chart with the chosen lines
        var regSel = document.getElementById('reg-model-select');
        if (regSel) {
            regSel.addEventListener('change', function () {
                renderAll();
                var r2Lin = document.getElementById('r2-linear');
                var r2Poly = document.getElementById('r2-poly');
                if (r2Lin) r2Lin.style.display = (regSel.value === 'poly') ? 'none' : '';
                if (r2Poly) r2Poly.style.display = (regSel.value === 'linear') ? 'none' : '';
            });
        }
    }

    // ── K-Means cluster scatter (2×2 grid) ──
    if (DATA.clustering) {
        register('ec-clusters', function (c) {
            var panels = [
                { title: 'Distance vs Pace', key: 'p', yName: 'Pace /500m', pace: true },
                { title: 'Distance vs Duration', key: 't', yName: 'Duration (min)' },
                { title: 'Distance vs Stroke Rate', key: 'spm', yName: 'Stroke Rate (spm)' },
                { title: 'Distance vs Calories', key: 'cal', yName: 'Calories (cal)' }
            ];
            var pos = [
                { left: '9%', top: '9%', width: '37%', height: '30%' },
                { left: '60%', top: '9%', width: '37%', height: '30%' },
                { left: '9%', top: '58%', width: '37%', height: '30%' },
                { left: '60%', top: '58%', width: '37%', height: '30%' }
            ];
            var titleTops = ['4%', '4%', '53%', '53%'];
            var grids = [], xAxes = [], yAxes = [], series = [], titles = [];

            panels.forEach(function (p, i) {
                grids.push(pos[i]);
                titles.push({ text: p.title, textStyle: { color: c.textSoft, fontSize: 13, fontWeight: 600 },
                              left: pos[i].left, top: titleTops[i] });
                xAxes.push(Object.assign({ type: 'value', gridIndex: i, name: i >= 2 ? 'Distance (m)' : '',
                    nameLocation: 'middle', nameGap: 26, nameTextStyle: { color: c.textSoft },
                    axisLabel: { color: c.textSoft, formatter: function (v) { return v >= 1000 ? (v / 1000) + 'k' : v; } } }, {
                    axisLine: { lineStyle: { color: c.axis } },
                    splitLine: { lineStyle: { color: c.grid } } }));
                var y = Object.assign({ type: 'value', gridIndex: i, scale: true, name: p.yName,
                    nameLocation: 'middle', nameGap: 52, nameTextStyle: { color: c.textSoft },
                    axisLabel: { color: c.textSoft } }, {
                    axisLine: { lineStyle: { color: c.axis } },
                    splitLine: { lineStyle: { color: c.grid } } });
                if (p.pace) {
                    y.inverse = true;
                    y.axisLabel.formatter = fmtPaceTick;
                }
                yAxes.push(y);
            });

            DATA.clustering.series.forEach(function (s, si) {
                var color = clusterColor(s.label, si);
                panels.forEach(function (p, pi) {
                    var pts = s.points
                        .filter(function (pt) { return pt[p.key] != null; })
                        .map(function (pt) { return [pt.d, pt[p.key]]; });
                    series.push({
                        name: s.label, type: 'scatter', xAxisIndex: pi, yAxisIndex: pi,
                        data: pts, symbolSize: 9,
                        itemStyle: { color: color, opacity: 0.75 }
                    });
                });
            });

            // Fix title tops for percentage-positioned rows
            return Object.assign(baseOption(c), {
                title: titles,
                legend: { bottom: 0, textStyle: { color: c.textSoft } },
                tooltip: Object.assign(baseOption(c).tooltip, {
                    trigger: 'item',
                    formatter: function (p) {
                        var y = p.value[1];
                        var isPacePanel = series[p.seriesIndex].yAxisIndex === 0;
                        var yTxt = isPacePanel ? fmtPace(y) + ' /500m' : y;
                        return p.marker + ' ' + p.seriesName + '<br>' +
                               p.value[0].toLocaleString() + ' m · <b>' + yTxt + '</b>';
                    }
                }),
                grid: grids, xAxis: xAxes, yAxis: yAxes, series: series
            });
        });
    }

    // ── Training balance pie ──
    if (DATA.cluster_pie) {
        register('ec-pie', function (c) {
            var d = DATA.cluster_pie;
            return Object.assign(baseOption(c), {
                title: { text: 'Training Balance', left: 'center', textStyle: { color: c.text, fontSize: 15 } },
                tooltip: Object.assign(baseOption(c).tooltip, {
                    formatter: function (p) { return p.marker + ' ' + p.name + ': <b>' + p.value + '</b> (' + p.percent + '%)'; }
                }),
                legend: { bottom: 0, textStyle: { color: c.textSoft } },
                series: [{
                    type: 'pie', radius: ['38%', '68%'], center: ['50%', '48%'],
                    data: d.labels.map(function (l, i) {
                        return { name: l, value: d.values[i], itemStyle: { color: clusterColor(l, i) } };
                    }),
                    label: { color: c.textSoft, formatter: '{b}\n{d}%' },
                    itemStyle: { borderColor: isDark() ? '#1a2029' : '#ffffff', borderWidth: 2, borderRadius: 4 },
                    emphasis: { scale: true, scaleSize: 6 }
                }]
            });
        });
    }

    // ── Workout distribution: KDE curve + percentile markers ──
    if (DATA.distribution) {
        var MARKER_COLORS = [PALETTE.green, PALETTE.sky, PALETTE.indigo, PALETTE.indigoMuted];

        register('ec-distribution', function (c) {
            var sel = document.getElementById('dist-metric-select');
            var key = sel && DATA.distribution.metrics[sel.value] ? sel.value : Object.keys(DATA.distribution.metrics)[0];
            var m = DATA.distribution.metrics[key];
            var isPace = !!m.pace;

            function fmtVal(v) {
                return isPace ? fmtPace(v) + ' ' + m.unit : v + ' ' + m.unit;
            }

            var yMax = Math.max.apply(null, m.y);
            var markLines = m.markers.map(function (mk, i) {
                return {
                    xAxis: mk.value,
                    lineStyle: { color: MARKER_COLORS[i], width: i === 0 ? 2.5 : 1.6, type: i === 0 ? 'solid' : 'dashed' },
                    label: {
                        formatter: mk.label + '\n' + (isPace ? fmtPaceTick(mk.value) : mk.value),
                        color: MARKER_COLORS[i], fontSize: 11, fontWeight: i === 0 ? 700 : 500,
                        position: i % 2 === 0 ? 'end' : 'insideEndTop'
                    }
                };
            });

            var noun = key === 'weekly' ? 'weeks' : (key === 'monthly' ? 'months' : 'sessions');

            return Object.assign(baseOption(c), {
                title: { text: m.label + ' — density of ' + m.n + ' ' + noun, left: 'center',
                         textStyle: { color: c.text, fontSize: 15 } },
                tooltip: Object.assign(baseOption(c).tooltip, {
                    trigger: 'axis',
                    formatter: function (ps) {
                        return fmtVal(ps[0].value[0]);
                    }
                }),
                grid: { left: 50, right: 30, top: 70, bottom: 50 },
                xAxis: Object.assign({ type: 'value', min: 'dataMin', max: 'dataMax',
                    name: m.unit, nameLocation: 'middle', nameGap: 30,
                    nameTextStyle: { color: c.textSoft },
                    axisLabel: { color: c.textSoft, formatter: isPace ? fmtPaceTick : undefined } }, {
                    axisLine: { lineStyle: { color: c.axis } },
                    splitLine: { show: false } }),
                yAxis: { type: 'value', max: yMax * 1.25, axisLabel: { show: false },
                         splitLine: { show: false }, axisLine: { show: false }, axisTick: { show: false } },
                series: [{
                    type: 'line',
                    data: m.x.map(function (x, i) { return [x, m.y[i]]; }),
                    showSymbol: false, smooth: true,
                    lineStyle: { color: PALETTE.indigo, width: 2.5 },
                    areaStyle: {
                        color: {
                            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
                            colorStops: [
                                { offset: 0, color: 'rgba(99,121,242,0.45)' },
                                { offset: 1, color: 'rgba(99,121,242,0.03)' }
                            ]
                        }
                    },
                    markLine: {
                        symbol: 'none', animation: false,
                        data: markLines,
                        emphasis: { disabled: true }
                    }
                }]
            });
        });

        var distSel = document.getElementById('dist-metric-select');
        if (distSel) {
            // Hide metrics with no data (e.g. heart rate until a HR strap is used)
            Array.prototype.slice.call(distSel.options).forEach(function (opt) {
                if (!DATA.distribution.metrics[opt.value]) opt.remove();
            });
            distSel.addEventListener('change', renderAll);
        }
    }

    // ── Theme toggle (replaces the old Plotly repaint) ──
    var btn = document.getElementById('theme-toggle');
    if (btn) {
        btn.addEventListener('click', function () {
            var next = isDark() ? 'light' : 'dark';
            document.documentElement.setAttribute('data-theme', next);
            try { localStorage.setItem('theme', next); } catch (e) { /* storage blocked */ }
            renderAll();
        });
    }

    // ── Responsive resize ──
    var rt;
    window.addEventListener('resize', function () {
        clearTimeout(rt);
        rt = setTimeout(function () {
            registry.forEach(function (r) { if (r.chart) r.chart.resize(); });
        }, 150);
    });

    renderAll();
})();
