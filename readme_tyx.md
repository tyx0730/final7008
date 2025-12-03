# readme_tyx

目前修复了logs没有截图的问题，但有两个问题：

1.  google的人机验证如何绕过？
2.  我修改了prompt来完成PDF里的example task，让agent直接去arxiv里搜论文，但卡在搜索这一步

## 修改点

1. `prompt_templates.py`，修改通用提示词为arxiv.org专用版，为了完成example task
2. `planner.py`：
   1. **logs里没有截图和日志就是因为planner逻辑有问题**，在第一步就done了，所以只有output没有logs，新版本已修复
   2. 增加URL 自动稳定检测逻辑：如果卡住了（三步的URL都没有变化），直接done，避免卡死
3. `main.py`：设置最大步数为30（太小了不行，后期可再增加）