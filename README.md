# 会展布展协作平台

策展人、设计师和施工团队共同编排展位布局、展品运输与搭建进度，按同一版执行方案完成布展交付。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/WorkbenchView.vue|tsx  全部模块共享工作台
│   ├── src/data/modules.ts              18个业务模块配置
│   ├── src/api/              统一请求封装
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/resource.py  通用查询/导出/登记/动作接口
│   ├── app/services/<key>.py    每个模块独立领域逻辑
│   ├── app/services/quota_package.py  配额对账包：面积/功率同轮快照、排位签发
│   ├── app/services/base.py     共享服务骨架
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 场馆规划 | `venue` | 场馆 | 场馆名称、可用面积、层高限制 |
| 展位编排 | `booth` | 展位 | 展位编号、面积尺寸、开口方向 |
| 参展商管理 | `exhibitor` | 参展商 | 企业名称、展品类别、联系人 |
| 方案设计 | `design` | 设计方案 | 设计风格、结构材料、搭建高度 |
| 搭建物料 | `material` | 物料 | 物料名称、规格型号、配额数量 |
| 展品运输 | `transport` | 运输单 | 展品名称、运输方式、预计到达 |
| 搭建进度 | `construction` | 进度节点 | 节点名称、计划日期、完成日期 |
| 用电配置 | `electrical` | 用电回路 | 回路编号、额定功率、所属展位 |
| 安全巡检 | `safety` | 巡检记录 | 检查点位、隐患等级、整改措施 |
| 灯光编排 | `lighting` | 灯光方案 | 灯位坐标、色温设定、光束角度 |
| 影音布置 | `audio_visual` | 影音设备 | 设备型号、安装位置、信号线路 |
| 家具配置 | `furniture` | 家具方案 | 家具类型、摆放位置、数量需求 |
| 导视系统 | `signage` | 导视牌 | 指示内容、安装点位、尺寸规格 |
| 验收清单 | `checklist` | 验收项 | 验收条目、验收标准、负责班组 |
| 变更指令 | `change_order` | 变更单 | 变更内容、影响展位、施工班组 |
| 布展排期 | `schedule` | 排期计划 | 活动名称、布展起始、撤展截止 |
| 交场确认 | `handover` | 交场单 | 交出班组、接收人员、遗留事项 |
| 突发事件 | `incident` | 事件记录 | 事件类型、发生位置、处置班组 |

## 配额对账包

看板除即时汇总外，还支持把「面积占用 + 功率核验」封成同一轮的配额对账包，供展位编排复核和排位签发。

- `POST /api/exhibition/quota/packages` 保存对账包。允许只存面积（功率仍在核算时返回
  `核对未完成` 提示），包本身是只读快照，**不登记展位、不增加面积占用**。
- 保存/签发接受 `client_request_id`：响应中断后用同一值重试会拿回原包号，不重复建包。
- 同一场馆未完成的包会把新快照作为下一轮追加，包号不变；`GET .../packages/latest` 可刷新包号。
- `POST .../packages/{package_no}/complete` 补齐功率：在新一轮里**重新封存面积与功率**，
  两者同轮后才成为签发依据。场馆后续更正的余量（如 28㎡ → 12㎡）会在补齐轮生效，
  旧余量记入 `superseded_areas`。
- `GET .../packages/{package_no}` 主管凭包号回查面积明细、功率明细、所依据的现场版本与采用轮次。
- `GET .../packages/{package_no}/readiness` 只读核对结论；未完成时给提示，不阻断查询。
- `POST .../packages/{package_no}/placements` 凭包办排位：缺项的包返回 400 提示，
  不能凭缺一项的包办成新排位。

前端 `QuotaDashboardView` 内的「配额对账包」面板提供保存、包号回查、刷新最新包号、
补齐功率与凭包办排位。

## 约定

- 全部模块共享`frontend/src/views/WorkbenchView.vue|tsx`和一套资源路由。
- 每个模块仍保留独立`backend/app/services/<模块>.py`；纯前端保留
  `frontend/src/domain/<模块>.ts`，用于承载真实业务差异并维持36题位容量。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

领域：应用开发
子方向：web前端/全栈开发
