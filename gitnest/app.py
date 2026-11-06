import asyncio
from pathlib import Path
import flet as ft
from gitnest.database import initialize, repositories, save_repository, delete_repository, add_log, logs
from gitnest.security import save_token, get_token, delete_token
from gitnest.services import test_repository, remote_images, download_one, download_all, upload_folder, compare_folders, cache_remote_thumbnails
from gitnest.config import CACHE_DIR

class GitNestApp:
    def __init__(self, page: ft.Page):
        self.page=page
        self.page.title="GitNest"
        self.page.padding=20
        self.page.window.width=1220
        self.page.window.height=850
        self.page.theme_mode=ft.ThemeMode.SYSTEM
        self.selected_repo_id=None
        self.remote_items=[]
        self.local_folder=ft.TextField(label="本地图片目录", expand=True)
        self.status=ft.Text()
        self.repo_dropdown=ft.Dropdown(label="当前仓库", width=420, on_select=self.on_repo_change)
        self.gallery=ft.GridView(expand=True, runs_count=4, max_extent=220, child_aspect_ratio=0.9, spacing=12, run_spacing=12)
        self.repo_form=self.build_repo_page()
        self.workspace=self.build_workspace()
        self.history=self.build_history()
        self.body=ft.Container(expand=True, content=self.workspace)
        self.navigation=ft.NavigationRail(selected_index=0, label_type=ft.NavigationRailLabelType.ALL,
            destinations=[ft.NavigationRailDestination(icon=ft.Icons.GRID_VIEW,label="图片工作台"),
                          ft.NavigationRailDestination(icon=ft.Icons.SETTINGS,label="仓库配置"),
                          ft.NavigationRailDestination(icon=ft.Icons.HISTORY,label="操作记录")],
            on_change=self.navigate)
        self.page.add(ft.Row([self.navigation,ft.VerticalDivider(width=1),self.body],expand=True))
        self.refresh_repositories()

    def build_repo_page(self):
        self.platform=ft.Dropdown(label="平台",value="github",options=[ft.DropdownOption("github","GitHub"),ft.DropdownOption("gitee","Gitee")],width=160)
        self.owner=ft.TextField(label="Owner / 用户名",width=220)
        self.repo=ft.TextField(label="仓库名称",width=220)
        self.branch=ft.TextField(label="分支（留空自动使用默认分支）",value="",hint_text="例如 main、master；留空自动检测",width=240)
        self.base_path=ft.TextField(label="图片根目录",value="images",width=220)
        self.repo_name=ft.TextField(label="显示名称",width=220)
        self.token=ft.TextField(label="访问令牌（不会保存到普通配置文件）",password=True,can_reveal_password=True,expand=True)
        self.repo_message=ft.Text()
        self.repo_cards=ft.Column(spacing=8)
        return ft.Column(expand=True,scroll=ft.ScrollMode.AUTO,controls=[
            ft.Text("仓库配置",size=26,weight=ft.FontWeight.BOLD),
            ft.Text("使用访问令牌，不要填写 GitHub / Gitee 登录密码。令牌通过系统凭据库保存。",color=ft.Colors.GREY_600),
            ft.Row([self.platform,self.owner,self.repo,self.branch],wrap=True),
            ft.Row([self.repo_name,self.base_path],wrap=True),self.token,
            ft.Row([ft.Button("保存仓库",icon=ft.Icons.SAVE,on_click=self.save_repo),
                    ft.OutlinedButton("测试连接",icon=ft.Icons.LINK,on_click=self.test_repo),
                    ft.OutlinedButton("清空",on_click=self.clear_repo_form)],wrap=True),
            self.repo_message,ft.Divider(),ft.Text("已配置仓库",size=18,weight=ft.FontWeight.BOLD),self.repo_cards])

    def build_workspace(self):
        self.conflict=ft.Dropdown(label="上传冲突策略",value="skip",width=220,options=[
            ft.DropdownOption("skip","远程存在则跳过"),ft.DropdownOption("overwrite","覆盖远程文件"),
            ft.DropdownOption("rename","自动重命名")])
        self.commit_message=ft.TextField(label="Commit 信息",value="GitNest upload",expand=True)
        self.confirm_overwrite=ft.Checkbox(label="我确认覆盖远程同路径图片",value=False)
        self.preview_text=ft.Text(selectable=True)
        return ft.Column(expand=True,scroll=ft.ScrollMode.AUTO,controls=[
            ft.Text("图片工作台",size=26,weight=ft.FontWeight.BOLD),
            ft.Row([self.repo_dropdown,ft.OutlinedButton("刷新仓库",icon=ft.Icons.REFRESH,on_click=self.refresh_repositories)]),
            ft.Row([self.local_folder,ft.OutlinedButton("选择目录",icon=ft.Icons.FOLDER_OPEN,on_click=self.pick_folder)],wrap=True),
            ft.Row([ft.Button("读取远程图片",icon=ft.Icons.CLOUD_DOWNLOAD,on_click=self.load_remote),
                    ft.OutlinedButton("批量下载",icon=ft.Icons.DOWNLOAD,on_click=self.download_remote_all),
                    ft.Button("批量上传",icon=ft.Icons.CLOUD_UPLOAD,on_click=self.upload_local)],wrap=True),
            ft.Row([self.conflict,self.commit_message],wrap=True),self.confirm_overwrite,self.status,
            ft.Text("远程图片图库",size=18,weight=ft.FontWeight.BOLD),self.gallery,
            ft.Divider(),ft.Text("同步差异预览",size=18,weight=ft.FontWeight.BOLD),
            ft.OutlinedButton("比较本地与远程内容（SHA-256）",icon=ft.Icons.COMPARE_ARROWS,on_click=self.sync_preview),self.preview_text])

    def build_history(self):
        self.history_rows=ft.Column(spacing=4)
        return ft.Column(expand=True,scroll=ft.ScrollMode.AUTO,controls=[ft.Text("操作记录",size=26,weight=ft.FontWeight.BOLD),
            ft.OutlinedButton("刷新",icon=ft.Icons.REFRESH,on_click=self.refresh_history),self.history_rows])

    def navigate(self,e):
        index=e.control.selected_index
        self.body.content=[self.workspace,self.repo_form,self.history][index]
        if index==1:self.refresh_repo_cards()
        if index==2:self.refresh_history()
        self.page.update()

    def current_repo(self):
        rid=self.repo_dropdown.value
        if not rid: raise ValueError("请先配置并选择仓库")
        return next((r for r in repositories() if str(r["id"])==str(rid)),None) or (_ for _ in ()).throw(ValueError("仓库配置不存在"))

    def token_for(self,repo):
        token=get_token(repo)
        if not token: raise ValueError("系统凭据库中没有该仓库的 Token，请重新保存 Token")
        return token

    def refresh_repositories(self,e=None):
        rows=repositories()
        self.repo_dropdown.options=[ft.DropdownOption(str(r["id"]),f'{r["name"]} · {r["platform"]}') for r in rows]
        if rows and not any(str(r["id"])==str(self.repo_dropdown.value) for r in rows): self.repo_dropdown.value=str(rows[0]["id"])
        if self.page: self.page.update()
        self.refresh_repo_cards()

    def on_repo_change(self,e):
        self.remote_items=[]; self.gallery.controls.clear(); self.status.value="已切换仓库"; self.page.update()

    def form_data(self):
        owner=(self.owner.value or "").strip(); repo=(self.repo.value or "").strip()
        if not owner or not repo: raise ValueError("Owner 和仓库名称不能为空")
        branch=(self.branch.value or "").strip(); base=(self.base_path.value or "images").strip("/")
        if any(x in (".","..") for x in base.split("/")): raise ValueError("图片目录包含非法路径")
        return {"name":(self.repo_name.value or f"{owner}/{repo}").strip(),"platform":self.platform.value,
                "owner":owner,"repo":repo,"branch":branch,"base_path":base}

    def save_repo(self,e):
        try:
            data=self.form_data(); row=save_repository(data)
            if self.token.value.strip(): save_token(row,self.token.value.strip())
            self.token.value=""; self.repo_message.value="仓库配置已保存"
            self.refresh_repositories()
        except Exception as ex:self.repo_message.value=f"保存失败：{ex}"
        self.page.update()

    def test_repo(self,e):
        try:
            data=self.form_data(); token=self.token.value.strip()
            if not token: raise ValueError("测试连接前请填写 Token")
            test_repository(data,token); self.repo_message.value="连接成功：仓库和分支均可访问"
        except Exception as ex:self.repo_message.value=f"连接失败：{ex}"
        self.page.update()

    def clear_repo_form(self,e):
        for field in (self.owner,self.repo,self.repo_name,self.token):field.value=""
        self.repo_message.value="";self.page.update()

    def refresh_repo_cards(self):
        if not hasattr(self,"repo_cards"):return
        self.repo_cards.controls=[]
        for r in repositories():
            self.repo_cards.controls.append(ft.Card(content=ft.Container(padding=12,content=ft.Row([
                ft.Column([ft.Text(r["name"],weight=ft.FontWeight.BOLD),ft.Text(f'{r["platform"]} · {r["owner"]}/{r["repo"]} · {r["branch"]} · {r["base_path"]}',size=12)],expand=True),
                ft.OutlinedButton("删除配置",icon=ft.Icons.DELETE,on_click=lambda e,row=r:self.remove_repo(row))]))))
        if self.page:self.page.update()

    def remove_repo(self,row):
        delete_repository(row["id"]);delete_token(row);self.refresh_repositories()

    async def pick_folder(self,e):
        picker=ft.FilePicker()
        self.page.services.append(picker);self.page.update()
        selected=await picker.get_directory_path()
        if selected:self.local_folder.value=selected;self.page.update()

    async def run_background(self,fn,*args):
        self.status.value="正在处理，请稍候……";self.page.update()
        try:return await asyncio.to_thread(fn,*args)
        except Exception as ex:self.status.value=f"操作失败：{ex}";self.page.update();return None

    async def load_remote(self,e):
        try:
            repo=self.current_repo();items=await self.run_background(remote_images,repo,self.token_for(repo))
            if items is None:return
            self.remote_items=items;self.gallery.controls=[]
            self.status.value=f"已读取 {len(items)} 张图片，正在生成缩略图……"; self.page.update()
            cached=await self.run_background(cache_remote_thumbnails,repo,self.token_for(repo),items,str(CACHE_DIR))
            if cached is None:return
            self.gallery.controls=[]
            for item in items:
                entry=cached.get(item.path,{})
                image_control=(ft.Image(src=entry["thumbnail"],width=180,height=120,fit=ft.ImageFit.CONTAIN)
                               if entry.get("thumbnail") else
                               ft.Container(height=120,alignment=ft.Alignment.CENTER,
                                   content=ft.Column([ft.Icon(ft.Icons.BROKEN_IMAGE,size=36),
                                       ft.Text("缩略图不可用",size=11)],alignment=ft.MainAxisAlignment.CENTER)))
                card=ft.Container(border=ft.Border.all(1,ft.Colors.OUTLINE_VARIANT),border_radius=10,padding=8,
                    content=ft.Column([ft.Container(height=126,alignment=ft.Alignment.CENTER,content=image_control),
                        ft.Text(item.name,max_lines=1,overflow=ft.TextOverflow.ELLIPSIS,weight=ft.FontWeight.BOLD),
                        ft.Text(f"{item.size:,} bytes",size=11,color=ft.Colors.GREY_600),
                        ft.Row([ft.IconButton(ft.Icons.PREVIEW,tooltip="查看大图",on_click=lambda e,it=item:self.preview_image(it)),
                                ft.IconButton(ft.Icons.DOWNLOAD,tooltip="下载",on_click=lambda e,it=item:self.download_single(it))],alignment=ft.MainAxisAlignment.END)]))
                self.gallery.controls.append(card)
            failed=sum(1 for value in cached.values() if value.get("error"))
            self.status.value=f"远程读取完成：{len(items)} 张图片；缩略图失败 {failed} 张"
            self.page.update()
        except Exception as ex:self.status.value=f"读取失败：{ex}";self.page.update()

    async def preview_image(self,item):
        try:
            repo=self.current_repo()
            cached=await self.run_background(cache_remote_thumbnails,repo,self.token_for(repo),[item],str(CACHE_DIR))
            entry=(cached or {}).get(item.path,{})
            if entry.get("original"):
                self.page.show_dialog(ft.AlertDialog(title=ft.Text(item.name),content=ft.Image(src=entry["original"],width=620,height=480,fit=ft.ImageFit.CONTAIN),actions=[ft.TextButton("关闭",on_click=lambda e:self.page.pop_dialog())]))
            else:
                raise ValueError(entry.get("error") or "图片缓存失败")
        except Exception as ex:self.status.value=f"预览失败：{ex}";self.page.update()

    async def download_single(self,item):
        try:
            if not self.local_folder.value:raise ValueError("请先选择本地保存目录")
            repo=self.current_repo();result=await self.run_background(download_one,repo,self.token_for(repo),item.path,self.local_folder.value)
            if result:add_log(repo["id"],"download",item.path,"success",str(result));self.status.value=f"下载成功：{result}"
        except Exception as ex:self.status.value=f"下载失败：{ex}"
        self.page.update()

    async def download_remote_all(self,e):
        try:
            if not self.local_folder.value:raise ValueError("请先选择本地保存目录")
            if not self.remote_items:raise ValueError("请先读取远程图片")
            repo=self.current_repo();results=await self.run_background(download_all,repo,self.token_for(repo),self.local_folder.value,self.remote_items)
            if results is None:return
            ok=0
            for path,success,msg in results:
                good=success;ok+=int(good);add_log(repo["id"],"download",path,"success" if good else "failed",msg)
            self.status.value=f"批量下载完成：成功 {ok}，失败 {len(results)-ok}"
        except Exception as ex:self.status.value=f"下载失败：{ex}"
        self.page.update()

    async def upload_local(self,e):
        try:
            if not self.local_folder.value:raise ValueError("请先选择本地图片目录")
            repo=self.current_repo()
            if self.conflict.value=="overwrite" and not self.confirm_overwrite.value:
                raise ValueError("覆盖模式会替换远程同路径文件，请先勾选覆盖确认")
            results=await self.run_background(upload_folder,repo,self.token_for(repo),self.local_folder.value,self.conflict.value,self.commit_message.value or "GitNest upload")
            self.confirm_overwrite.value=False
            if results is None:return
            counts={"uploaded":0,"skipped":0,"failed":0}
            for path,state,msg in results:
                counts[state]=counts.get(state,0)+1;add_log(repo["id"],"upload",path,state,msg)
            self.status.value=f"上传结束：成功 {counts['uploaded']}，跳过 {counts['skipped']}，失败 {counts['failed']}"
        except Exception as ex:self.status.value=f"上传失败：{ex}"
        self.page.update()

    async def sync_preview(self,e):
        try:
            if not self.local_folder.value:raise ValueError("请先选择本地目录")
            if not self.remote_items:raise ValueError("请先读取远程图片")
            repo=self.current_repo();rows=await self.run_background(compare_folders,repo,self.token_for(repo),self.local_folder.value,self.remote_items)
            if rows is None:return
            labels={"local_only":"仅本地（建议上传）","remote_only":"仅远程（建议下载）",
                    "same":"内容一致","different":"内容不同（冲突）","error":"比对失败（需重试）"}
            lines=[]
            for row in rows:
                line=f"{labels[row['status']]} | {row['path']}"
                if row.get("local_size") is not None or row.get("remote_size") is not None:
                    line+=f"\n  本地：{row.get('local_size','-')} bytes；远程：{row.get('remote_size','-')} bytes"
                if row.get("local_sha256") or row.get("remote_sha256"):
                    line+=f"\n  本地 SHA-256：{row.get('local_sha256') or '-'}\n  远程 SHA-256：{row.get('remote_sha256') or '-'}"
                if row.get("error"):line+=f"\n  错误：{row['error']}"
                lines.append(line)
            counts={key:sum(1 for row in rows if row['status']==key) for key in labels}
            summary="比较结果："+"；".join(f"{labels[k]} {v}" for k,v in counts.items() if v)
            self.preview_text.value=summary+"\n\n"+"\n\n".join(lines) if rows else "两端没有图片文件"
        except Exception as ex:self.preview_text.value=f"比较失败：{ex}"
        self.page.update()

    def refresh_history(self,e=None):
        self.history_rows.controls=[]
        for row in logs():
            self.history_rows.controls.append(ft.ListTile(title=ft.Text(f"{row['action']} · {row['file_path']} · {row['status']}"),
                subtitle=ft.Text(f"{row['repository_name'] or '仓库'} · {row['message']} · {row['created_at']}")))
        self.page.update()

def main(page: ft.Page):
    initialize()
    GitNestApp(page)
