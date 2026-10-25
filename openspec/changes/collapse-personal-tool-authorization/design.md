# Design

## Context

参见proposal。Store.authorize_tool已解析原task/plan、检查取消、调用所有execution guards、委派权限和selected tool。个人工具目前额外调用同一执行guard链及bindings.recheck。

## Goals / Non-Goals

目标：每次callback只走一次完整执行guard链。非目标：减少独立callback、缓存权限、改变MCP期限或证明所有历史超时均已修复。

## Decisions

ExecutionBindings提供符合四参guard契约的require_execution，main注册该绑定方法。个人工具检查注册guard等于ExecutionBindings类上原方法绑定到当前bindings对象，不能以实例上替换的方法自证相等。随后调用Store.authorize_tool一次，确认返回plan id/owner等于捕获的原plan，再检查retained handle。固定function/call/run/adapter/descriptor检查保持。

不选任意lambda身份缓存，因为不能证明初始guard的真实语义；不引入跨callback授权缓存，也不使用REPEATABLE READ事务包裹授权。凭据解析前后各保留独立完整授权，handle本身仍独立校验。

## Risks / Trade-offs

缺失guard的自定义装配将明确拒绝，而不是悄悄绕过绑定。便携fixture须装配相同可信方法契约。检查仍非撤权与外部dispatch的原子事务；此次不扩大原保证。

调用次数验证仅证明重复路径消除；真实PG原失败用例保持原期限和断言，保留首失败，单次绿不能关闭历史偶发原因。
