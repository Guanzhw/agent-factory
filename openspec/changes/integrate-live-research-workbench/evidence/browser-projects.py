import json
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect
out=Path('/tmp/af-live-browser');out.mkdir(exist_ok=True)
project={'id':'project-1','ownerId':'alice','title':'图像分类稳定性研究','state':'ready','assistantId':'assistant-1','currentGoalVersion':1,'createdAt':'2026-10-25T12:00:00Z','ending':None,'execution':{'available':False,'reason':'RESEARCH_ORIGINAL_ATTEMPT_REQUIRED'},'goals':[{'version':1,'createdAt':'2026-10-25T12:00:00Z','confirmedAt':'2026-10-25T12:01:00Z','agreement':{'objective':'研究不同采样方法对分类误差的影响','evaluation':'相同评估集，多次独立测量；结果须保留种子与配置','stopConditions':'达标或预算耗尽时停止；技术失败单独记录','resourceRefs':{},'budget':{'rounds':3,'toolCalls':8,'tokenLimit':None,'amountMicros':None,'currency':None}}}]}
results=[]
with sync_playwright() as p:
 b=p.chromium.launch(headless=True)
 for width,height in [(1487,1058),(390,844)]:
  c=b.new_context(viewport={'width':width,'height':height});page=c.new_page();errors=[];console=[];writes=[]
  page.on('pageerror',lambda e:errors.append(str(e)))
  page.on('console',lambda m:console.append(m.text) if m.type=='error' else None)
  def fixture(route):
   path=urlparse(route.request.url).path
   data={
    '/auth/config':{'enabled':False,'loginPath':'/api/factory/auth/login','logoutPath':'/api/factory/auth/logout'},'/status':{'mode':'demo','maxWorkers':1,'activeWorkers':0,'queuedJobs':0,'liveEnabled':False,'integration':'Synthetic browser fixture'},
    '/session':{'id':'alice','name':'Alice','role':'user'},'/materials':[], '/jobs':{'items':[],'nextCursor':None},'/execution-targets':[],
    '/research/projects/project-1/experiments':{'items':[],'rounds':[{'id':'round-original','goalVersion':1,'taskId':'task-original','decision':None,'terminal':None,'terminalRecordId':None}]},'/research/setup':{'workflowPin':{'kind':'workflow','id':'research-round','revision':'1','sha256':'a'*64},'models':[],'connections':[],'environments':[],'experimentMaterials':[]},'/applications':[],'/user-connections':[],
    '/personal-models/capabilities':{'enabled':False,'providers':[],'liveCompatibilityVerified':False},'/personal-models':[],
    '/user-connections/registrations':[], '/resources/leases':{'leases':[],'nextCursor':None},
    '/personal-credentials/capabilities':{'enabled':False,'providerIds':[]},'/personal-ssh/capabilities':{'enabled':False},
    '/personal-tools/descriptors':[], '/personal-tools':[], '/personal-remotes/providers':[], '/personal-remotes':[],
    '/research/projects':{'items':[project],'nextCursor':None},'/research/projects/project-1':project,'/assistants':{'items':[],'nextCursor':None}}
   key=path.removeprefix('/api/factory')
   if route.request.method!='GET':writes.append(path);raise AssertionError(path)
   assert key in data,path
   route.fulfill(json=data[key])
  page.route('**/api/**',fixture)
  page.goto('http://127.0.0.1:4176/')
  try: expect(page.get_by_role('heading',name='应用目录',exact=True)).to_be_visible()
  except Exception:
   print({'errors':errors,'console':console,'text':page.locator('body').inner_text()},flush=True);page.screenshot(path=str(out/'failure.png'));raise
  page.get_by_role('button',name='进入 AutoResearch',exact=True).click()
  expect(page.get_by_role('heading',name='图像分类稳定性研究',exact=True)).to_be_visible()
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
  page.screenshot(path=str(out/f'workbench-{width}.png'))
  page.locator('.rw-project-row').click()
  expect(page.get_by_role('heading',name='项目详情',exact=True)).to_be_visible()
  page.get_by_role('button',name='修改目标',exact=True).click()
  expect(page.get_by_role('form',name='研究约定',exact=True)).to_be_visible()
  page.get_by_role('button',name='取消修订',exact=True).click()
  page.get_by_role('button',name='配置研究执行',exact=True).click()
  expect(page.get_by_text('尚无可选的已发布应用。请先在应用管理中保存并发布适用的研究执行定义。')).to_be_visible()
  page.get_by_role('button',name='准备新的研究执行配置',exact=True).click()
  expect(page.get_by_text('缺少已注册运行环境。需要先完成实际运行环境注册，不能用演示环境替代。')).to_be_visible()
  expect(page.get_by_role('button',name='保存私人配置草稿')).to_be_disabled()
  page.get_by_role('button',name='取消配置',exact=True).click()
  page.get_by_role('tab',name='证据',exact=True).click()
  expect(page.get_by_text('尚无助手研究决策；运行完成不等于目标达成。')).to_be_visible()
  page.reload()
  expect(page.get_by_role('tab',name='证据',exact=True)).to_have_attribute('aria-selected','true')
  page.get_by_role('button',name='资源',exact=True).click()
  page.get_by_role('button',name='设置我的模型/API',exact=True).click()
  page.get_by_role('button',name='管理我的凭据与连接',exact=True).click()
  page.get_by_role('button',name='管理模型/API 设置',exact=True).click()
  page.get_by_role('button',name='返回工作区',exact=True).click()
  expect(page.get_by_role('heading',name='项目详情',exact=True)).to_be_visible()
  expect(page.get_by_role('tab',name='证据',exact=True)).to_have_attribute('aria-selected','true')
  page.get_by_role('button',name='返回工作台',exact=True).click()
  page.go_back();expect(page.get_by_role('heading',name='项目详情',exact=True)).to_be_visible()
  page.go_forward();expect(page.get_by_role('heading',name='我的研究',exact=True)).to_be_visible()
  page.get_by_role('button',name='新建项目',exact=True).click()
  expect(page.get_by_role('dialog',name='建立研究项目')).to_be_visible()
  page.keyboard.press('Escape')
  expect(page.get_by_role('dialog')).to_have_count(0)
  assert page.get_by_role('button',name='新建项目',exact=True).evaluate('(el)=>el===document.activeElement')
  if width==390:
   page.get_by_role('button',name='研究助手',exact=True).click();expect(page.get_by_role('dialog',name='研究助手')).to_be_visible();page.keyboard.press('Escape')
  page.get_by_role('button',name='返回平台',exact=True).click();expect(page.get_by_role('heading',name='应用目录',exact=True)).to_be_visible()
  assert not errors,errors
  assert not console,console
  results.append({'viewport':[width,height],'result':'passed','pageErrors':errors,'consoleErrors':console,'writes':writes,'identity':'synthetic transport only, no real research execution'})
  c.close()
 b.close()
(out/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2));print(json.dumps(results,ensure_ascii=False))
