// Mermaid 直接渲染初始化
// 不使用任何插件，直接初始化 Mermaid 并处理所有图表

(function() {
    // 等待 DOM 加载完成
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initMermaid);
    } else {
        initMermaid();
    }

    function initMermaid() {
        // 检查是否存在 mermaid 对象
        if (typeof mermaid !== 'undefined') {
            try {
                // 初始化 Mermaid
                mermaid.initialize({
                    startOnLoad: true,
                    securityLevel: 'loose',
                    theme: 'default',
                    themeVariables: {
                        primaryColor: '#1976d2',
                        primaryTextColor: '#fff',
                        primaryBorderColor: '#154578',
                        lineColor: '#f8b229',
                        secondaryColor: '#006100',
                        tertiaryColor: '#fff'
                    },
                    flowchart: {
                        useMaxWidth: true,
                        htmlLabels: true,
                        curve: 'basis'
                    },
                    sequence: {
                        useMaxWidth: true,
                        wrap: true
                    },
                    gantt: {
                        useMaxWidth: true
                    },
                    class: {
                        useMaxWidth: true
                    },
                    journey: {
                        useMaxWidth: true
                    },
                    state: {
                        useMaxWidth: true
                    },
                    er: {
                        useMaxWidth: true
                    }
                });

                console.log('Mermaid 已初始化，等待自动渲染...');

            } catch (error) {
                console.error('Mermaid 初始化失败:', error);
            }
        } else {
            console.warn('Mermaid 库未加载');
        }
    }

    // 延迟 2 秒后手动触发渲染
    setTimeout(function() {
        if (typeof mermaid !== 'undefined') {
            try {
                console.log('尝试手动渲染所有 Mermaid 图表...');
                mermaid.run();
                console.log('Mermaid 手动渲染已触发');
            } catch (err) {
                console.error('Mermaid run() 失败:', err);
            }
        }
    }, 2000);
})();
