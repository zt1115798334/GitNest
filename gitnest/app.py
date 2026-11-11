import asyncio
from pathlib import Path
import flet as ft
from gitnest.database import initialize, repositories, save_repository, delete_repository, add_log, logs, create_upload_task, update_upload_task, upload_task_rows, get_upload_task
from gitnest.security import save_token, get_token, delete_token
from gitnest.services import test_repository, remote_images, download_one, download_all, upload_paths, compare_folders, cache_remote_thumbnails, UploadControl
from gitnest.image_cache import save_remote_image
from gitnest.images import scan_images
from gitnest.config import CACHE_DIR

class GitNestApp:
    def __init__(self, page: ft.Page):
        self.page=page
        self.page.title="GitNest"
        self.page.padding=0
        self.page.window.width=1360
        self.page.window.height=900
        self.page.theme_mode=ft.ThemeMode.LIGHT
        self.page.bgcolor="#F4F6FA"
        self.page.theme=ft.Theme(color_scheme_seed="#3765E8",use_material3=True)
        self.selected_repo_id=None
        self.remote_items=[]
        self.local_files=[]
        self.local_mode='files'
        self.local_root=None
        self.file_picker=ft.FilePicker()
        self.page.services.append(self.file_picker)
        self.remote_subpath=ft.TextField(label='远程子目录（可选）', hint_text='例如：2026/旅行照片', width=260)
        self.upload_progress=ft.ProgressBar(value=0, width=320, visible=False)
        self.upload_details=ft.Text(selectable=True, size=12, color=ft.Colors.GREY_700, visible=False)
        self.upload_queue_rows=[]
        self.queue_display=ft.Text(selectable=True,size=12,color=ft.Colors.GREY_700,visible=False)
        self.active_upload_control=None
        self.active_task_id=None
        self.active_task_payload=None
        self.pause_upload_button=ft.OutlinedButton("暂停上传",icon=ft.Icons.PAUSE,on_click=self.pause_upload,disabled=True)
        self.resume_upload_button=ft.OutlinedButton("继续上传",icon=ft.Icons.PLAY_ARROW,on_click=self.resume_upload,disabled=True)
        self.cancel_upload_button=ft.OutlinedButton("取消任务",icon=ft.Icons.CANCEL,on_click=self.cancel_upload,disabled=True)
        self.saved_tasks=ft.Column(spacing=4)
        self.retry_failed_button=ft.OutlinedButton("重试失败任务",icon=ft.Icons.REFRESH,on_click=self.retry_failed_uploads,visible=False)
        self.remote_cache={}
        self.remote_search=ft.TextField(label="搜索图片名称或路径",prefix_icon=ft.Icons.SEARCH,width=280,on_change=self.filter_remote_gallery)
        self.remote_type=ft.Dropdown(label="格式",width=130,value="all",options=[
            ft.DropdownOption("all","全部格式"),ft.DropdownOption("jpg","JPG"),ft.DropdownOption("png","PNG"),
            ft.DropdownOption("webp","WEBP"),ft.DropdownOption("gif","GIF"),ft.DropdownOption("other","其他")],
            on_select=self.filter_remote_gallery)
        self.remote_sort=ft.Dropdown(label="排序",width=150,value="name_asc",options=[
            ft.DropdownOption("name_asc","名称升序"),ft.DropdownOption("name_desc","名称降序"),
            ft.DropdownOption("size_desc","文件最大优先"),ft.DropdownOption("size_asc","文件最小优先")],
            on_select=self.filter_remote_gallery)
        self.remote_count=ft.Text(color=ft.Colors.GREY_600,size=12)
        self.local_summary=ft.Text('尚未选择图片', color=ft.Colors.GREY_600)
        self.local_gallery=ft.GridView(expand=False, height=260, runs_count=4, max_extent=190, child_aspect_ratio=0.9, spacing=10, run_spacing=10, visible=False)
        self.local_folder=ft.TextField(label="本地图片目录", expand=True)
        self.status=ft.Text()
        self.repo_dropdown=ft.Dropdown(label="当前仓库", width=420, on_select=self.on_repo_change)
        self.gallery=ft.GridView(expand=False, height=320, runs_count=4, max_extent=220, child_aspect_ratio=0.9, spacing=12, run_spacing=12, visible=False)
        self.repo_form=self.build_repo_page()
        self.workspace=self.build_workspace()
        self.history=self.build_history()
        self.body=ft.Container(expand=True,padding=28,bgcolor="#F4F6FA",content=self.workspace)
        self.navigation=ft.NavigationRail(selected_index=0,label_type=ft.NavigationRailLabelType.ALL,
            min_width=156,group_alignment=-0.9,bgcolor="#FFFFFF",
            indicator_color="#EAF0FF",use_indicator=True,
            selected_label_text_style=ft.TextStyle(color="#315DDB",weight=ft.FontWeight.W_600,size=12),
            unselected_label_text_style=ft.TextStyle(color="#778196",size=12),
            destinations=[
                ft.NavigationRailDestination(icon=ft.Icons.GRID_VIEW_OUTLINED,selected_icon=ft.Icons.GRID_VIEW,label="图片工作台"),
                ft.NavigationRailDestination(icon=ft.Icons.SETTINGS_OUTLINED,selected_icon=ft.Icons.SETTINGS,label="仓库配置"),
                ft.NavigationRailDestination(icon=ft.Icons.HISTORY_OUTLINED,selected_icon=ft.Icons.HISTORY,label="操作记录")],
            on_change=self.navigate)
        sidebar=ft.Container(width=184,bgcolor="#FFFFFF",padding=ft.Padding(12,22,12,16),
            content=ft.Column(expand=True,spacing=18,controls=[
                ft.Container(padding=ft.Padding(12,8,8,18),content=ft.Row(spacing=10,controls=[
                    ft.Container(width=34,height=34,border_radius=11,bgcolor="#EAF0FF",
                        alignment=ft.Alignment.CENTER,content=ft.Icon(ft.Icons.PHOTO_LIBRARY_ROUNDED,color="#315DDB",size=20)),
                    ft.Column(spacing=0,controls=[
                        ft.Text("GitNest",size=19,weight=ft.FontWeight.BOLD,color="#202B3C"),
                        ft.Text("IMAGE WORKSPACE",size=9,weight=ft.FontWeight.W_600,color="#8993A5")
                    ])
                ])),
                ft.Text("工作空间",size=10,weight=ft.FontWeight.BOLD,color="#9AA3B2"),
                ft.Container(expand=True,content=self.navigation),
                ft.Container(expand=True),
                ft.Divider(color="#EDF0F5"),
                ft.Container(padding=10,content=ft.Column(spacing=3,controls=[
                    ft.Text("GitNest Desktop",size=11,weight=ft.FontWeight.W_600,color="#566174"),
                    ft.Text("图片仓库管理工具",size=10,color="#9AA3B2")
                ]))
            ]))
        self.page.add(ft.SafeArea(expand=True,content=ft.Row([
            sidebar,
            ft.VerticalDivider(width=1,color="#E9EDF3"),
            self.body
        ],spacing=0,expand=True)))
        self.refresh_repositories()
        self.refresh_saved_tasks()

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
        return ft.Column(expand=True,scroll=ft.ScrollMode.AUTO,spacing=16,controls=[
            ft.Column(spacing=5,controls=[
                ft.Text("仓库配置",size=30,weight=ft.FontWeight.BOLD,color="#202B3C"),
                ft.Text("管理 GitHub 与 Gitee 仓库连接，访问令牌安全保存在系统凭据库。",size=12,color="#7A8495")
            ]),
            ft.Container(padding=22,border_radius=16,bgcolor="#FFFFFF",border=ft.Border.all(1,"#E7EBF2"),
                content=ft.Column(spacing=14,controls=[
            ft.Row([self.platform,self.owner,self.repo,self.branch],wrap=True),
            ft.Row([self.repo_name,self.base_path],wrap=True),self.token,
            ft.Row([ft.Button("保存仓库",icon=ft.Icons.SAVE,on_click=self.save_repo),
                    ft.OutlinedButton("测试连接",icon=ft.Icons.LINK,on_click=self.test_repo),
                    ft.OutlinedButton("清空",on_click=self.clear_repo_form)],wrap=True),
            self.repo_message
                ])),
            ft.Container(padding=22,border_radius=16,bgcolor="#FFFFFF",border=ft.Border.all(1,"#E7EBF2"),
                content=ft.Column(spacing=12,controls=[
                    ft.Text("已配置仓库",size=18,weight=ft.FontWeight.BOLD,color="#202B3C"),
                    self.repo_cards
                ]))
        ])

    def build_workspace(self):
        self.conflict=ft.Dropdown(label="同名文件处理",value="skip",width=220,on_select=self.on_conflict_change,options=[
            ft.DropdownOption("skip","跳过已存在文件"),ft.DropdownOption("overwrite","覆盖远程文件"),
            ft.DropdownOption("rename","自动重命名")])
        self.commit_message=ft.TextField(label="提交说明",value="GitNest image upload",width=280)
        self.confirm_overwrite=ft.Checkbox(label="我确认覆盖远程同路径图片",value=False,visible=False)
        self.preview_text=ft.Text(selectable=True)
        self.status=ft.Text("选择仓库和本地图片，即可开始管理",color=ft.Colors.GREY_600)
        self.upload_button=ft.Button("上传所选图片",icon=ft.Icons.CLOUD_UPLOAD,on_click=self.upload_selected,disabled=True)
        self.folder_upload_button=ft.OutlinedButton("上传整个目录",icon=ft.Icons.FOLDER_OPEN,on_click=self.upload_local,disabled=True)
        self.local_section=ft.Container(
            padding=20,border_radius=16,bgcolor="#FFFFFF",border=ft.Border.all(1,"#E7EBF2"),
            content=ft.Column(spacing=12,controls=[
                ft.Row([ft.Column([
                    ft.Text("本地图片",size=18,weight=ft.FontWeight.BOLD),
                    ft.Text("支持多选图片或扫描整个目录；上传前可预览和移除文件。",size=12,color=ft.Colors.GREY_600)
                ],expand=True),self.local_summary]),
                ft.Row([
                    ft.Button("选择图片",icon=ft.Icons.ADD_PHOTO_ALTERNATE,on_click=self.pick_files),
                    ft.OutlinedButton("选择目录",icon=ft.Icons.FOLDER_OPEN,on_click=self.pick_folder),
                    ft.TextButton("清空选择",icon=ft.Icons.CLEAR,on_click=self.clear_local_selection),
                    self.upload_button,
                    self.folder_upload_button,
                    self.upload_progress
                ],wrap=True),
                self.local_folder,
                self.local_gallery,
            ])
        )
        self.remote_section=ft.Container(
            padding=20,border_radius=16,bgcolor="#FFFFFF",border=ft.Border.all(1,"#E7EBF2"),
            content=ft.Column(spacing=10,controls=[
                ft.Row([ft.Column([
                    ft.Text("远程图片库",size=18,weight=ft.FontWeight.BOLD),
                    ft.Text("浏览仓库中的图片，支持搜索、格式筛选、排序、预览和下载。",size=12,color=ft.Colors.GREY_600)
                ],expand=True),ft.OutlinedButton("读取远程图片",icon=ft.Icons.REFRESH,on_click=self.load_remote),
                    ft.OutlinedButton("批量下载",icon=ft.Icons.DOWNLOAD,on_click=self.download_remote_all)]),
                ft.Row([self.remote_search,self.remote_type,self.remote_sort,self.remote_count],wrap=True,spacing=10),
                self.gallery
            ])
        )
        return ft.Column(expand=True,scroll=ft.ScrollMode.AUTO,spacing=16,controls=[
            ft.Row([
                ft.Column([
                    ft.Text("图片工作台",size=30,weight=ft.FontWeight.BOLD,color="#202B3C"),
                    ft.Text("管理本地图片与 GitHub / Gitee 仓库之间的上传、下载和同步。",size=12,color="#7A8495")
                ],expand=True,spacing=5),
                self.repo_dropdown,
                ft.IconButton(ft.Icons.REFRESH,tooltip="刷新仓库列表",on_click=self.refresh_repositories)
            ],vertical_alignment=ft.CrossAxisAlignment.CENTER),
            self.local_section,
            ft.Container(padding=20,border_radius=16,bgcolor="#FFFFFF",border=ft.Border.all(1,"#E7EBF2"),
                content=ft.Column(spacing=12,controls=[
                    ft.Row([ft.Column([ft.Text("上传设置",size=18,weight=ft.FontWeight.BOLD,color="#202B3C"),
                        ft.Text("设置远程目录、文件冲突规则和提交说明",size=11,color="#8993A5")],spacing=3),
                        ft.Container(expand=True),ft.Icon(ft.Icons.TUNE_ROUNDED,color="#8B95A6")]),
                    ft.Row([self.remote_subpath,self.conflict,self.commit_message],wrap=True,spacing=10),
                    self.confirm_overwrite,
                    self.status,
                    self.queue_display,
                    ft.Row([self.pause_upload_button,self.resume_upload_button,self.cancel_upload_button],wrap=True),
                    self.retry_failed_button,
                    self.upload_details,
                    ft.Divider(color="#EDF0F5"),
                    ft.Row([ft.Text("任务中心",size=14,weight=ft.FontWeight.BOLD,color="#344054"),
                        ft.Container(expand=True),
                        ft.Text("可暂停、恢复和重试",size=10,color="#8993A5")]),
                    ft.Container(padding=12,border_radius=12,bgcolor="#F8FAFC",content=self.saved_tasks)
                ])),
            self.remote_section,
            ft.Container(padding=20,border_radius=16,bgcolor="#FFFFFF",border=ft.Border.all(1,"#E7EBF2"),
                content=ft.Column(spacing=10,controls=[
                    ft.Text("同步差异",size=18,weight=ft.FontWeight.BOLD),
                    ft.Text("按文件内容 SHA-256 比较本地和远程图片，不会自动删除任何文件。",size=12,color=ft.Colors.GREY_600),
                    ft.OutlinedButton("比较本地与远程内容",icon=ft.Icons.COMPARE_ARROWS,on_click=self.sync_preview),
                    self.preview_text
                ]))
        ])

    def on_conflict_change(self,e):
        self.confirm_overwrite.visible=self.conflict.value=="overwrite"
        if not self.confirm_overwrite.visible:
            self.confirm_overwrite.value=False
        self.page.update()

    def build_history(self):
        self.history_rows=ft.Column(spacing=4)
        return ft.Column(expand=True,scroll=ft.ScrollMode.AUTO,spacing=16,controls=[
            ft.Row([ft.Column([ft.Text("操作记录",size=30,weight=ft.FontWeight.BOLD,color="#202B3C"),
                ft.Text("查看图片上传、下载和仓库操作的执行结果。",size=12,color="#7A8495")],spacing=5),
                ft.Container(expand=True),ft.OutlinedButton("刷新记录",icon=ft.Icons.REFRESH,on_click=self.refresh_history)]),
            ft.Container(padding=20,border_radius=16,bgcolor="#FFFFFF",border=ft.Border.all(1,"#E7EBF2"),
                content=self.history_rows)
        ])

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

    async def pick_files(self,e=None):
        try:
            files=await self.file_picker.pick_files(
                dialog_title="选择要上传的图片",
                allow_multiple=True,
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["jpg","jpeg","png","gif","webp","bmp","tif","tiff","avif"],
            )
            if not files:
                return
            paths=[Path(item.path) for item in files if item.path]
            if not paths:
                raise ValueError("文件选择器没有返回本地文件路径")
            self.local_mode="files"
            self.local_root=None
            self.local_folder.value=""
            await self.set_local_files(paths)
        except Exception as ex:
            self.status.value=f"选择图片失败：{ex}"
            self.page.update()

    async def set_local_files(self,paths):
        unique=[]
        seen=set()
        for value in paths:
            path=Path(value).expanduser().resolve()
            if path.is_file() and path not in seen:
                unique.append(path);seen.add(path)
        self.local_files=unique
        self.local_gallery.visible=bool(unique)
        self.local_gallery.controls=[]
        self.upload_button.disabled=not unique
        self.folder_upload_button.disabled=not (self.local_mode=="folder" and unique)
        self.local_summary.value=f"已选择 {len(unique)} 张图片"
        self.page.update()
        preview_errors=[]
        for path in unique:
            try:
                content=await self.run_background(lambda p: p.read_bytes(),path)
                if content is None:
                    raise ValueError("读取文件失败，请检查文件是否仍存在或被其他程序占用")
                cached=await self.run_background(
                    save_remote_image,content,f"local/{path}",str(CACHE_DIR/"local")
                )
                if not cached:
                    raise ValueError("缩略图生成失败，请检查图片格式或文件是否损坏")
                _,thumbnail=cached
                card=ft.Container(
                    padding=8,border_radius=12,border=ft.Border.all(1,ft.Colors.OUTLINE_VARIANT),
                    content=ft.Column(spacing=6,controls=[
                        ft.Container(height=112,alignment=ft.Alignment.CENTER,
                            content=ft.Image(src=thumbnail.read_bytes(),width=160,height=108,fit=ft.BoxFit.CONTAIN)),
                        ft.Text(path.name,size=12,weight=ft.FontWeight.BOLD,max_lines=1,overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Text(f"{path.stat().st_size:,} bytes",size=10,color=ft.Colors.GREY_600),
                        ft.Row([ft.IconButton(ft.Icons.CLOSE,tooltip="从上传列表移除",
                            on_click=lambda e,p=path:self.remove_local_file(p))],alignment=ft.MainAxisAlignment.END)
                    ])
                )
            except Exception as exc:
                preview_errors.append(f"{path.name}: {exc}")
                card=ft.Container(
                    padding=8,border_radius=12,border=ft.Border.all(1,ft.Colors.OUTLINE_VARIANT),
                    content=ft.Column(spacing=6,controls=[
                        ft.Container(height=112,alignment=ft.Alignment.CENTER,
                            content=ft.Icon(ft.Icons.BROKEN_IMAGE,color=ft.Colors.RED,size=36)),
                        ft.Text(path.name,size=12,weight=ft.FontWeight.BOLD,max_lines=1,overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Text(f"预览失败：{exc}",size=10,color=ft.Colors.RED,max_lines=3),
                        ft.IconButton(ft.Icons.CLOSE,tooltip="从上传列表移除",
                            on_click=lambda e,p=path:self.remove_local_file(p))
                    ])
                )
            self.local_gallery.controls.append(card)
            self.page.update()
        self.status.value=f"本地图片已加入队列：{len(self.local_files)} 张"
        if preview_errors:
            self.status.value+=f"；其中 {len(preview_errors)} 张预览失败，但仍可尝试上传"
        self.page.update()

    def remove_local_file(self,path):
        self.local_files=[item for item in self.local_files if item!=path]
        self.local_summary.value=f"已选择 {len(self.local_files)} 张图片"
        self.local_gallery.controls=[]
        self.page.update()
        async def redraw():
            await self.set_local_files(self.local_files)
        self.page.run_task(redraw)

    def clear_local_selection(self,e=None):
        self.local_files=[]
        self.local_gallery.visible=False
        self.local_mode="files"
        self.local_root=None
        self.local_folder.value=""
        self.local_gallery.controls.clear()
        self.local_summary.value="尚未选择图片"
        self.upload_details.value=""
        self.upload_button.disabled=True
        self.folder_upload_button.disabled=True
        self.status.value="已清空本地图片选择"
        self.page.update()

    async def upload_selected(self,e=None):
        try:
            if not self.local_files:
                raise ValueError("请先选择图片或目录")
            repo=self.current_repo()
            if self.conflict.value=="overwrite" and not self.confirm_overwrite.value:
                raise ValueError("覆盖模式会替换远程同路径文件，请先勾选覆盖确认")
            if self.local_mode=="files":
                names=[p.name.casefold() for p in self.local_files]
                if len(names)!=len(set(names)):
                    raise ValueError("所选文件中存在同名图片。请分批选择，或改为选择目录以保留子目录结构")
            payload={
                "repository_id":repo["id"],
                "paths":[str(p) for p in self.local_files],
                "relative_to":str(self.local_root) if self.local_mode=="folder" and self.local_root else None,
                "conflict":self.conflict.value,
                "commit_message":self.commit_message.value or "GitNest image upload",
                "remote_subpath":self.remote_subpath.value or "",
                "completed":{}
            }
            task_id=create_upload_task(repo["id"],payload)
            self.active_task_id=task_id
            await self.execute_upload_task(task_id,payload,repo)

        except Exception as ex:
            self.status.value=f"上传失败：{ex}"
            self.page.update()

    async def execute_upload_task(self,task_id,payload,repo):
        if self.active_upload_control is not None:
            self.status.value="当前已有上传任务正在运行，请先完成或取消当前任务"
            self.page.update()
            return
        paths=[Path(p) for p in payload.get("paths",[])]
        completed=payload.setdefault("completed",{})
        remaining=[p for p in paths if completed.get(str(p),{}).get("state") not in {"uploaded","skipped"}]
        if not remaining:
            update_upload_task(task_id,payload=payload,status="completed",summary="所有图片均已处理")
            self.refresh_saved_tasks()
            self.status.value="任务已完成，没有待上传文件"
            self.page.update()
            return
        self.active_task_id=task_id
        self.active_task_payload=payload
        self.active_upload_control=UploadControl()
        self.upload_queue_rows=[
            {"path":str(p),"state":completed.get(str(p),{}).get("state","queued"),
             "message":completed.get(str(p),{}).get("message","等待上传")} for p in paths
        ]
        self.upload_button.disabled=True
        self.folder_upload_button.disabled=True
        self.upload_progress.visible=True
        self.upload_progress.value=0
        self.retry_failed_button.visible=False
        self.pause_upload_button.disabled=False
        self.resume_upload_button.disabled=True
        self.cancel_upload_button.disabled=False
        self.status.value=f"任务 #{task_id} 正在上传，剩余 {len(remaining)} 张"
        update_upload_task(task_id,payload=payload,status="running",summary=f"正在上传，剩余 {len(remaining)} 张")
        self.refresh_upload_queue()
        self.refresh_saved_tasks()
        loop=asyncio.get_running_loop()
        control=self.active_upload_control
        def progress_callback(index,total,path,state,message):
            if state in {"uploaded","skipped","failed"} and 0 < index <= len(remaining):
                completed[str(remaining[index-1].resolve())]={"state":state,"message":message}
                update_upload_task(task_id,payload=payload,summary=f"已处理 {len(completed)} 项")
            overall_index=paths.index(remaining[index-1])+1 if 0 < index <= len(remaining) else index
            loop.call_soon_threadsafe(self.update_upload_progress,overall_index,len(paths),path,state,message)
        try:
            results=await self.run_background(
                upload_paths,repo,self.token_for(repo),remaining,
                payload.get("conflict","skip"),payload.get("commit_message","GitNest image upload"),
                payload.get("remote_subpath",""),payload.get("relative_to"),
                progress_callback=progress_callback,control=control
            )
            if results is None:
                update_upload_task(task_id,payload=payload,status="failed",summary="上传执行异常，请检查日志")
                return
            for index,(path,state,msg) in enumerate(results):
                if index < len(remaining):
                    completed[str(remaining[index].resolve())]={"state":state,"message":msg}
                add_log(repo["id"],"upload",path,state,msg)
            cancelled=control.cancelled
            paused=control.paused and not cancelled
            failed=sum(1 for value in completed.values() if value.get("state")=="failed")
            pending=[p for p in paths if completed.get(str(p.resolve()),{}).get("state") not in {"uploaded","skipped"}]
            if not pending:
                status="completed";summary="全部图片已处理"
            elif cancelled:
                status="cancelled";summary=f"用户取消任务，仍有 {len(pending)} 张未处理"
            elif paused:
                status="paused";summary=f"已暂停，剩余 {len(pending)} 张"
            else:
                status="failed";summary=f"有 {len(pending)} 张未成功处理，其中失败 {failed} 张；可继续重试"
            update_upload_task(task_id,payload=payload,status=status,summary=summary)
            self.status.value=f"任务 #{task_id}：{summary}"
            self.upload_details.value=summary
            self.upload_details.visible=True
            self.retry_failed_button.visible=status=="failed"
            self.confirm_overwrite.value=False
            self.upload_progress.value=1 if status=="completed" else 0
            if any(value.get("state")=="uploaded" for value in completed.values()):
                self.remote_items=[];self.remote_cache={};self.gallery.controls.clear();self.gallery.visible=False
        except Exception as ex:
            update_upload_task(task_id,payload=payload,status="failed",summary=f"任务异常：{ex}")
            self.status.value=f"任务 #{task_id} 执行失败：{ex}"
        finally:
            self.active_upload_control=None
            self.active_task_payload=None
            self.active_task_id=None
            self.pause_upload_button.disabled=True
            self.resume_upload_button.disabled=True
            self.cancel_upload_button.disabled=True
            self.upload_progress.visible=False
            self.upload_button.disabled=not self.local_files
            self.folder_upload_button.disabled=not (self.local_mode=="folder" and bool(self.local_files))
            self.refresh_upload_queue()
            self.refresh_saved_tasks()
            self.page.update()

    def pause_upload(self,e=None):
        if self.active_upload_control is None:return
        self.active_upload_control.pause()
        if self.active_task_id is not None and self.active_task_payload is not None:
            update_upload_task(self.active_task_id,payload=self.active_task_payload,status="paused",summary="暂停请求已发送，当前文件结束后暂停")
        self.pause_upload_button.disabled=True
        self.resume_upload_button.disabled=False
        self.status.value="正在完成当前图片，随后暂停……"
        self.page.update()

    def resume_upload(self,e=None):
        if self.active_upload_control is None:return
        self.active_upload_control.resume()
        if self.active_task_id is not None and self.active_task_payload is not None:
            update_upload_task(self.active_task_id,payload=self.active_task_payload,status="running",summary="继续上传中")
        self.pause_upload_button.disabled=False
        self.resume_upload_button.disabled=True
        self.status.value="继续上传中……"
        self.page.update()

    def cancel_upload(self,e=None):
        if self.active_upload_control is None:return
        self.active_upload_control.cancel()
        self.pause_upload_button.disabled=True
        self.resume_upload_button.disabled=True
        self.cancel_upload_button.disabled=True
        self.status.value="正在停止任务（当前正在进行的单张图片请求结束后生效）……"
        self.page.update()

    def refresh_saved_tasks(self):
        if not hasattr(self,"saved_tasks"):return
        self.saved_tasks.controls=[]
        rows=upload_task_rows(30)
        for task in rows:
            state=task["status"]
            can_resume=state in {"paused","failed","queued"}
            self.saved_tasks.controls.append(ft.Container(padding=8,border=ft.Border.all(1,ft.Colors.OUTLINE_VARIANT),
                border_radius=8,content=ft.Row([
                    ft.Column([ft.Text(f"任务 #{task['id']} · {state}",weight=ft.FontWeight.BOLD),
                               ft.Text(task["summary"],size=11,color=ft.Colors.GREY_600),
                               ft.Text(task["created_at"],size=10,color=ft.Colors.GREY_500)],expand=True),
                    ft.OutlinedButton("继续 / 重试",disabled=not can_resume or self.active_upload_control is not None,
                        on_click=lambda e,tid=task["id"]:self.resume_saved_task(tid))
                ])))
        if not rows:
            self.saved_tasks.controls=[ft.Text("暂无历史上传任务",size=12,color=ft.Colors.GREY_500)]
        if self.page:self.page.update()

    async def resume_saved_task(self,task_id):
        if self.active_upload_control is not None:
            self.status.value="请先暂停或结束当前任务"
            self.page.update()
            return
        task=get_upload_task(task_id)
        if not task:
            self.status.value="找不到该上传任务"
            self.page.update()
            return
        repo=next((r for r in repositories() if r["id"]==task["repository_id"]),None)
        if not repo:
            self.status.value="原仓库配置已删除，无法恢复该任务"
            self.page.update()
            return
        payload=task["payload"]
        self.local_files=[Path(p) for p in payload.get("paths",[])]
        self.local_root=Path(payload["relative_to"]) if payload.get("relative_to") else None
        self.local_mode="folder" if self.local_root else "files"
        self.conflict.value=payload.get("conflict","skip")
        self.remote_subpath.value=payload.get("remote_subpath","")
        self.commit_message.value=payload.get("commit_message","GitNest image upload")
        self.local_summary.value=f"恢复任务 #{task_id}：{len(self.local_files)} 张图片"
        missing=[p for p in payload.get("paths",[]) if not Path(p).is_file()]
        if missing:
            self.status.value=f"有 {len(missing)} 个原文件已不存在，请恢复原文件后再继续"
            self.page.update()
            return
        await self.execute_upload_task(task_id,payload,repo)

    async def pick_folder(self,e):
        try:
            selected=await self.file_picker.get_directory_path(dialog_title="选择包含图片的目录")
            if not selected:return
            self.local_folder.value=selected
            self.local_root=Path(selected).expanduser().resolve()
            self.local_mode="folder"
            files=await self.run_background(scan_images,selected)
            if files is None:return
            if not files:
                self.clear_local_selection()
                raise ValueError("该目录及其子目录中没有找到支持的图片")
            await self.set_local_files(files)
            self.folder_upload_button.disabled=False
            self.status.value=f"已扫描目录：找到 {len(files)} 张图片（保留目录结构）"
            self.page.update()
        except Exception as ex:
            self.status.value=f"选择目录失败：{ex}"
            self.page.update()

    def update_upload_progress(self,index,total,path,state,message=""):
        self.upload_progress.value=((index-1)/total if state=="uploading" else index/total) if total else 1
        labels={"uploading":"正在上传","uploaded":"已上传","skipped":"已跳过","failed":"失败"}
        self.status.value=f"上传进度 {index}/{total} · {labels.get(state,state)}：{path}"
        if 0 < index <= len(self.upload_queue_rows):
            row=self.upload_queue_rows[index-1]
            row["state"]=state
            row["message"]=message
            self.refresh_upload_queue()
        self.page.update()

    async def run_background(self,fn,*args,**kwargs):
        self.status.value="正在处理，请稍候……";self.page.update()
        try:return await asyncio.to_thread(fn,*args,**kwargs)
        except Exception as ex:self.status.value=f"操作失败：{ex}";self.page.update();return None

    async def load_remote(self,e):
        try:
            repo=self.current_repo()
            items=await self.run_background(remote_images,repo,self.token_for(repo))
            if items is None:return
            self.remote_items=items
            self.remote_cache={}
            self.gallery.controls=[]
            self.gallery.visible=False
            self.status.value=f"已读取 {len(items)} 张图片，正在生成缩略图……"
            self.page.update()
            cached=await self.run_background(cache_remote_thumbnails,repo,self.token_for(repo),items,str(CACHE_DIR))
            if cached is None:return
            self.remote_cache=cached
            self.render_remote_gallery()
            failed=sum(1 for value in cached.values() if value.get("error"))
            self.status.value=f"远程读取完成：{len(items)} 张图片；缩略图失败 {failed} 张"
            self.page.update()
        except Exception as ex:
            self.status.value=f"读取失败：{ex}"
            self.page.update()

    def filter_remote_gallery(self,e=None):
        self.render_remote_gallery()

    def render_remote_gallery(self):
        query=(self.remote_search.value or "").strip().casefold()
        image_items=[]
        for item in self.remote_items:
            suffix=Path(item.name).suffix.lower().lstrip(".")
            kind=suffix if suffix in {"jpg","jpeg","png","webp","gif"} else "other"
            selected=self.remote_type.value or "all"
            if selected!="all" and not (
                selected=="jpg" and kind in {"jpg","jpeg"} or selected=="other" and kind=="other" or kind==selected
            ):
                continue
            if query and query not in item.name.casefold() and query not in item.path.casefold():
                continue
            image_items.append(item)
        sort_mode=self.remote_sort.value or "name_asc"
        if sort_mode=="name_desc":
            image_items.sort(key=lambda x:x.name.casefold(),reverse=True)
        elif sort_mode=="size_desc":
            image_items.sort(key=lambda x:x.size,reverse=True)
        elif sort_mode=="size_asc":
            image_items.sort(key=lambda x:x.size)
        else:
            image_items.sort(key=lambda x:x.name.casefold())
        self.gallery.controls=[]
        self.gallery.visible=bool(image_items)
        self.remote_count.value=f"显示 {len(image_items)} / 共 {len(self.remote_items)} 张"
        for item in image_items:
            entry=self.remote_cache.get(item.path,{})
            image_control=(ft.Image(src=entry["thumbnail"],width=180,height=120,fit=ft.BoxFit.CONTAIN)
                           if entry.get("thumbnail") else
                           ft.Container(height=120,alignment=ft.Alignment.CENTER,
                               content=ft.Column([ft.Icon(ft.Icons.BROKEN_IMAGE,size=36),
                                   ft.Text("缩略图不可用",size=11)],alignment=ft.MainAxisAlignment.CENTER)))
            card=ft.Container(border=ft.Border.all(1,ft.Colors.OUTLINE_VARIANT),border_radius=10,padding=8,
                content=ft.Column([ft.Container(height=126,alignment=ft.Alignment.CENTER,content=image_control),
                    ft.Text(item.name,max_lines=1,overflow=ft.TextOverflow.ELLIPSIS,weight=ft.FontWeight.BOLD),
                    ft.Text(f"{item.size:,} bytes",size=11,color=ft.Colors.GREY_600),
                    ft.Text(item.path,size=10,color=ft.Colors.GREY_500,max_lines=2,overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Row([ft.IconButton(ft.Icons.PREVIEW,tooltip="查看大图",on_click=lambda e,it=item:self.preview_image(it)),
                            ft.IconButton(ft.Icons.DOWNLOAD,tooltip="下载",on_click=lambda e,it=item:self.download_single(it))],
                           alignment=ft.MainAxisAlignment.END)]))
            self.gallery.controls.append(card)
        self.page.update()

    def refresh_upload_queue(self):
        labels={"queued":"排队中","uploading":"正在上传","uploaded":"成功","skipped":"已跳过","failed":"失败"}
        lines=[]
        for row in self.upload_queue_rows:
            name=Path(row["path"]).name
            lines.append(f"[{labels.get(row['state'],row['state'])}] {name}  {row.get('message','')}")
        shown=lines[:30]
        if len(lines)>30:
            shown.append(f"……还有 {len(lines)-30} 个任务未展开")
        self.queue_display.value="上传任务队列：\n"+"\n".join(shown) if shown else ""
        self.queue_display.visible=bool(lines)
        if self.page:
            self.page.update()

    async def retry_failed_uploads(self,e=None):
        failed=[Path(row["path"]) for row in self.upload_queue_rows if row["state"]=="failed"]
        failed=[path for path in failed if path.is_file()]
        if not failed:
            self.status.value="没有可重试的失败任务（请检查原文件是否仍存在）"
            self.page.update()
            return
        self.local_files=failed
        self.local_summary.value=f"准备重试 {len(failed)} 张失败图片"
        await self.upload_selected(e)

    async def preview_image(self,item):
        try:
            repo=self.current_repo()
            cached=await self.run_background(cache_remote_thumbnails,repo,self.token_for(repo),[item],str(CACHE_DIR))
            entry=(cached or {}).get(item.path,{})
            if entry.get("original"):
                self.page.show_dialog(ft.AlertDialog(title=ft.Text(item.name),content=ft.Image(src=entry["original"],width=620,height=480,fit=ft.BoxFit.CONTAIN),actions=[ft.TextButton("关闭",on_click=lambda e:self.page.pop_dialog())]))
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
        if self.local_mode!="folder" or not self.local_root:
            self.status.value="请先选择本地图片目录"
            self.page.update()
            return
        await self.upload_selected(e)

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
