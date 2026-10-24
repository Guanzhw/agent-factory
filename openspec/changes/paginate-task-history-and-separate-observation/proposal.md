# 任务历史读取

## Why
现有最多100项的列表逐项构建完整原生详情，GET还承担生命周期写入。成员无法读取更早历史，单一区域失败会阻断其他区域刷新。

## What Changes
新增按成员隔离的keyset分页（默认50，最多100）、持久化摘要与真实观察时间；前端独立刷新并保留旧历史导航。收尾写入转交已有observer及显式reconciliation，包含远程原操作回执。

## Impact
涉及core Store/API/observer/delegation、远程读取与观察分离、科研投影和Web消费端。不增加执行队列或重派发策略；更新已有Draft97，与审计PR103隔离。
