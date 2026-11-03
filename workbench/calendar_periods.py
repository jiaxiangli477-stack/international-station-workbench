"""Closed calendar reporting windows in the platform's Asia/Shanghai timezone."""
from calendar import monthrange
from datetime import date,datetime,timedelta,timezone

SHANGHAI=timezone(timedelta(hours=8))

def kind(start,end):
    first,last=date.fromisoformat(start),date.fromisoformat(end)
    if first.weekday()==0 and (last-first).days==6:return 'week'
    if first.day==1 and first.year==last.year and first.month==last.month and last.day==monthrange(first.year,first.month)[1]:return 'month'
    raise ValueError('请选择完整自然周（周一至周日）或完整自然月（1日至月末），不使用滚动7/30天或未结束期间')

def window(mode=None,start=None,end=None,today=None):
    today=today or datetime.now(SHANGHAI).date()
    if mode in (None,'week','previous_week'):
        last=today-timedelta(days=today.weekday()+1);first=last-timedelta(days=6)
    elif mode in ('month','previous_month'):
        last=today.replace(day=1)-timedelta(days=1);first=last.replace(day=1)
    elif mode=='custom':
        try:first,last=date.fromisoformat(start or ''),date.fromisoformat(end or '')
        except (TypeError,ValueError):raise ValueError('请输入有效起止日期') from None
    else:raise ValueError('最近7天/本周未完结口径已停用，请选择自然周或自然月')
    kind(first.isoformat(),last.isoformat())
    if last>=today:raise ValueError('统计期间尚未结束，请选择完整自然周或自然月')
    return {'start':first.isoformat(),'end':last.isoformat()}

def chunks(start,end):
    kind(start,end);first,last=date.fromisoformat(start),date.fromisoformat(end)
    out=[]
    while first<=last:
        stop=min(first+timedelta(days=6),last);out.append({'start':first.isoformat(),'end':stop.isoformat()});first=stop+timedelta(days=1)
    return out

def dashboard_windows(as_of,n_weeks=4):
    latest=window('previous_week',today=as_of);end=date.fromisoformat(latest['end']);weeks=[]
    for index in range(n_weeks):
        stop=end-timedelta(days=7*index);start=stop-timedelta(days=6)
        weeks.append({'idx':index+1,'week_start':start.isoformat(),'week_end':stop.isoformat(),'tag':'w%d_%s-%s'%(index+1,start.strftime('%Y%m%d'),stop.strftime('%m%d'))})
    month=window('previous_month',today=as_of);first=date.fromisoformat(month['start']);last=date.fromisoformat(month['end'])
    return {'as_of':as_of.isoformat(),'weeks':weeks,'months':[{'key':'month%d'%last.month,'month_start':month['start'],'month_end':month['end'],'tag':'month%d_%s-%s'%(last.month,first.strftime('%Y%m%d'),last.strftime('%m%d'))}]}
