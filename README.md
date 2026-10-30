# sim-sentinel

一个一分钟跑一次的 Windows 计划任务，加一份只依赖文件的判定状态机。
它读仿真器自己写下的引擎日志（`<project>_p0.log`），在**跑完／跑挂／卡住**这三种状态第一次出现时，
往桌面推一条中文通知，并在磁盘上追加一行证据。

- **平台**：Windows 10 / 11
- **依赖**：Python 3.8 以上（只用标准库）、PowerShell 5.1（系统自带）
- **不做什么**：不查询求解器内部状态，不判断结果是否收敛或正确，不提交、不取消任何云端任务
- **代码量**：五个文件共 412 行（含配置样例），另附 90 行的端到端自测脚本

## 三条判据

整套工具只从日志取事实，由此推出三条判据，代码里每一处设计都能追到其中一条。

| 判据 | 含义 |
|---|---|
| 只认文件，不猜 | 不向求解器查询内部状态；没有日志就没有结论 |
| 只报转变，不报轮询 | 每个日志记住已宣告过的状态，一次运行只弹一条 |
| 只认产物，不认回显 | 心跳时间戳、产物修改时间、只追加的事件记录才算证据；脚本自己打印「成功」不算 |

## 安装

```
<ROOT>\
├─ sim\                         仿真工程，*_p0.log 在这里（递归扫描）
├─ sentinel\                    sentinel.py / toast.ps1 / config.json
├─ launch\                      sentinel_run.cmd / register_tasks.ps1
├─ logs\                        state.json / events.jsonl / toast.log / 心跳
└─ _selftest_kit.ps1            端到端自测
```

三步：

1. `sentinel\config.example.json` 复制为 `config.json`，把 `root` 改成上面的 `<ROOT>`。
2. `launch\sentinel_run.cmd` 里 `set PY=` 那一行改成解释器路径（这一行不能带行尾注释）。
3. `powershell -ExecutionPolicy Bypass -File launch\register_tasks.ps1`（先加 `-Preview` 看配置，`-Remove` 卸载）。

注册时三个设置不能省，缺任何一个任务都会「看起来在运行」而什么都不做：

| 设置 | 缺了会怎样 |
|---|---|
| `-AllowStartIfOnBatteries` / `-DontStopIfGoingOnBatteries` | 笔记本拔电后不再触发，且不报错 |
| `-MultipleInstances IgnoreNew` | 一次实例卡住，之后每分钟的触发全被静默丢弃 |
| `-ExecutionTimeLimit <有限值>` | 默认上限七十二小时，卡住的实例永不释放 |

## 你会看到什么

一条通知：

```
仿真完成：gc_taper_p0.log
耗时 41分07秒　进度 99.4%
sim\gc_taper\gc_taper_p0.log
```

一行证据（只追加，永远不改）：

```json
{"ts": "2026-10-29 17:34:52", "kind": "FINISHED", "log": "sim\\gc_taper\\gc_taper_p0.log",
 "pct": "99.4%", "last": "total FDTD solver speed on 10 processes (Mnodes/s): 214.5", "toast_rc": 0}
```

判定词表里有两处反直觉的地方，改代码前先读 `sentinel/sentinel.py` 顶部注释：
`Auto Shutoff` 是自动关断阈值而不是完成标记（它印在每一行进度里），
完成行可能停在 99.4%（所以「等到 100%」不成立）。

## 自测

```
powershell -ExecutionPolicy Bypass -File _selftest_kit.ps1
```

它把工具箱复制到临时目录，造四个假日志、按顺序运行十次，断言「该静默时静默、该报时只报一次」，
测完删除沙箱（`-Keep` 保留）。不发通知，不写真实状态。期望输出：

```
PASS  finished log, FIRST sight -> silent baseline   expect=0 got=0
PASS  same log again -> still silent (dedupe)        expect=0 got=0
PASS  progress only -> no verdict                    expect=0 got=0
PASS  error appears in same log -> FAILED fires once  expect=1 got=1
PASS  FAILED again -> deduped                        expect=1 got=1
PASS  unchanged size x3 polls -> STALLED (4th run)    expect=2 got=2
PASS  pause marker -> polling skipped                 expect=2 got=2
RESULT: ALL PASS
```

## 实测读数

每一行都带适用范围 —— 脱离范围的数字在本主题里没有意义。

| 指标 | 读数 | 适用范围 |
|---|---|---|
| 判定规则用例 | 6/6 通过 | 2026-09-26，单机 |
| 真实日志回放 | 77 个 → FINISHED 68 / FAILED 1 / UNKNOWN 8 | 同日，一次性重判当时那棵工作树 |
| 单次轮询覆盖 | 503 个日志文件 | 2026-10-22 09:15 的健康报告 |
| 心跳连续性 | 13 个连续分钟时间戳（15:22:02 → 15:34:02） | 当时机器，无人干预 |
| 端到端自测 | 7/7 断言通过 | 2026-10-29 与 2026-10-31 各一次，本机临时目录 |
| 卡住指纹 | `State=Running` + `Last Result=267009` | 0x00041301，实例仍在运行 |

## 适用范围与已知缺陷

- **只覆盖 Windows。** 应用标识、任务调度器、进程列表都是 Windows 专有；换到 Linux，状态机与判定词表可原样复用，替换 `cron` 与 `notify-send` 两处外壳。
- **只覆盖本机。** 云端任务（例如 Tidy3D 云端求解）的日志不在本地，需要另开一条只读轮询：只查任务状态，不提交、不取消；凭据放在仓外的本机文件里。本仓不含这条通道。
- **不判断物理是否正确。** 它回答「跑完了没有」，不回答「结果对不对」。
- **首见静默有代价。** 一次运行若恰好在两次轮询之间完成、且日志随后被清理，那条通知永远收不到。一分钟轮询加十五分钟时间窗把概率压得很低，但不是零。
- **当前没有任何计划任务在运行。** 这套工具在 2026 年 9 至 10 月间于一台 Windows 机器上真实跑过；本仓是可复跑的重建版 —— 路径全部来自 `config.json`，迁移目录后不必再改常量。历史版本把路径写在常量里，搬家后全部失效。
- **通知可见性取决于系统设置。** 专注助手、发送方开关、策略都能静默吞掉横幅。工具只能记录「调用成功」，不能记录「人看到」。

## 引用

仓库内 `CITATION.cff` 是本仓的引用信息。归档编号（DOI）在第一次正式发布后由存档服务生成，届时会写回该文件；
在此之前，本仓没有可引用的编号，引用时请写明仓库地址与访问日期。

问题与建议走仓库的 issue。这是一个个人工具，回复不保证时效；如果你改了判定词表去适配另一款求解器，
把那段词表与它对应的日志原文一起贴出来，比描述现象有用。

## Licence

代码（`*.py`、`*.ps1`、`*.cmd`、`*.json`）为 MIT，见 `LICENSE`。
本文件与仓库内的说明文字为 CC BY 4.0，见 `LICENSE-docs.md`。

## English

A one-minute Windows scheduled task plus a file-only state machine. It reads the engine log a
simulation solver writes itself (`<project>_p0.log`), raises one Chinese toast the first time a run
is seen to finish, fail or stall, and appends one JSON line per verdict as evidence.

- Windows 10/11; Python 3.8+ (standard library only); PowerShell 5.1.
- It never queries the solver, never judges whether a result is converged or correct, and never
  submits or cancels a cloud task.
- Verdict vocabulary lives in `sentinel/sentinel.py`; `Auto Shutoff` is a threshold printed on every
  progress line and is not a completion marker, and a finished run may stop at 99.4%.
- `_selftest_kit.ps1` reproduces the seven assertions in a throw-away sandbox under `%TEMP%`;
  `RESULT: ALL PASS` is the expected output.
- No scheduled task is registered by this repository, and nothing here is a claim about any
  machine currently running it.

Code is MIT; the prose in this README is CC BY 4.0.
