import asyncio
from pathlib import Path
from threading import Lock
import flet as ft
from gitnest.database import initialize, repositories, save_repository, delete_repository, add_log, logs, create_upload_task, update_upload_task, upload_task_rows, get_upload_task, get_settings, set_setting
from gitnest.security import save_token, get_token, delete_token
from gitnest.services import test_repository, remote_images, download_one, download_all, upload_paths, compare_folders, cache_remote_thumbnails, UploadControl
from gitnest.image_cache import create_local_thumbnail
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
        self.remote_subpath=ft.TextField(label='远程子目录（可选）', hint_text='例如：2026/旅行照片', width=260,on_change=self.save_preferences)
        self.upload_progress=ft.ProgressBar(value=0, width=320, visible=False)
        self.upload_details=ft.Text(selectable=True, size=12, color=ft.Colors.GREY_700, visible=False)
        self.upload_queue_rows=[]
        self.queue_expanded=True
        self.queue_summary=ft.Text("上传任务队列",size=13,weight=ft.FontWeight.BOLD,color="#344054")
        self.queue_toggle=ft.IconButton(icon=ft.Icons.EXPAND_LESS,tooltip="收起上传任务队列",on_click=self.toggle_upload_queue)
        self.queue_list=ft.Column(spacing=4,scroll=ft.ScrollMode.AUTO)
        self.queue_body=ft.Container(
            height=280,
            padding=ft.Padding(10,6,10,6),
            border=ft.Border.all(1,"#E7EBF2"),
            border_radius=10,
            bgcolor="#FAFBFD",
            content=self.queue_list,
            visible=True
        )
        self.queue_panel=ft.Column(spacing=6,controls=[
            ft.Row([self.queue_summary,ft.Container(expand=True),self.queue_toggle]),
            self.queue_body
        ],visible=False)
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
        self.local_empty=ft.Text('选择图片或目录后，这里会显示图片预览。',size=12,color=ft.Colors.GREY_500)
        self.local_gallery=ft.GridView(expand=False, height=260, runs_count=4, max_extent=190, child_aspect_ratio=0.9, spacing=10, run_spacing=10, visible=False)
        self.local_load_more=ft.TextButton("加载更多",on_click=self.load_more_local_previews,visible=False)
        self.local_folder=ft.TextField(label="上传 / 同步本地目录", expand=True)
        self.download_folder=ft.TextField(label="远程图片下载到本地目录",expand=True,read_only=True)
        self.download_conflict=ft.Dropdown(label="下载同名文件",width=180,value="skip",options=[
            ft.DropdownOption("skip","跳过本地文件"),ft.DropdownOption("rename","自动重命名"),
            ft.DropdownOption("overwrite","覆盖本地文件")],on_select=self.on_download_conflict_change)
        self.confirm_download_overwrite=ft.Checkbox(label="我确认覆盖本地同名文件",value=False,visible=False)
        self.download_workers=ft.Dropdown(label="下载并发",value="4",width=130,on_select=self.save_preferences,options=[
            ft.DropdownOption("1","1 线程"),ft.DropdownOption("2","2 线程"),
            ft.DropdownOption("3","3 线程"),ft.DropdownOption("4","4 线程"),
            ft.DropdownOption("6","6 线程"),ft.DropdownOption("8","8 线程")])
        self.status=ft.Text()
        self.repo_dropdown=ft.Dropdown(label="当前仓库", width=420, on_select=self.on_repo_change)
        self.gallery=ft.GridView(expand=False, height=320, runs_count=4, max_extent=220, child_aspect_ratio=0.9, spacing=12, run_spacing=12, visible=False)
        self.remote_empty=ft.Text('尚未读取远程图片。点击“读取远程图片”开始浏览。',size=12,color=ft.Colors.GREY_500)
        self.repo_form=self.build_repo_page()
        self.workspace=self.build_workspace()
        self.history=self.build_history()
        self.restore_preferences()
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
        self.commit_message=ft.TextField(label="提交说明",value="GitNest image upload",width=280,on_change=self.save_preferences)
        self.upload_workers=ft.Dropdown(label="上传并发",value="3",width=130,on_select=self.save_preferences,options=[
            ft.DropdownOption("1","1 线程"),ft.DropdownOption("2","2 线程"),
            ft.DropdownOption("3","3 线程"),ft.DropdownOption("4","4 线程"),
            ft.DropdownOption("5","5 线程")])
        self.confirm_overwrite=ft.Checkbox(label="我确认覆盖远程同路径图片",value=False,visible=False)
        self.preview_text=ft.Text(selectable=True)
        self.sync_rows=[]
        self.sync_selected=set()
        self.sync_result_list=ft.Column(spacing=6)
        self.sync_upload_button=ft.Button("上传选中项",icon=ft.Icons.CLOUD_UPLOAD,on_click=self.sync_upload_selected,disabled=True)
        self.sync_download_button=ft.OutlinedButton("下载选中项",icon=ft.Icons.DOWNLOAD,on_click=self.sync_download_selected,disabled=True)
        self.sync_selection_summary=ft.Text("尚未选择同步项目",size=12,color=ft.Colors.GREY_600)
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
                self.local_empty,
                self.local_gallery,
                self.local_load_more,
            ])
        )
        self.remote_section=ft.Container(
            padding=20,border_radius=16,bgcolor="#FFFFFF",border=ft.Border.all(1,"#E7EBF2"),
            content=ft.Column(spacing=10,controls=[
                ft.Row([ft.Column([
                    ft.Text("远程图片库",size=18,weight=ft.FontWeight.BOLD),
                    ft.Text("浏览仓库中的图片，支持搜索、格式筛选、排序、预览和下载。",size=12,color=ft.Colors.GREY_600)
                ],expand=True),ft.OutlinedButton("读取远程图片",icon=ft.Icons.REFRESH,on_click=self.load_remote),
                    ft.OutlinedButton("批量下载",icon=ft.Icons.DOWNLOAD,on_click=self.download_remote_all)],wrap=True),
                ft.Row([self.download_folder,ft.OutlinedButton("选择下载目录",icon=ft.Icons.FOLDER_OPEN,on_click=self.pick_download_folder),self.download_conflict,self.download_workers],wrap=True),
                self.confirm_download_overwrite,
                ft.Row([self.remote_search,self.remote_type,self.remote_sort,self.remote_count],wrap=True,spacing=10),
                self.remote_empty,
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
                    ft.Row([self.remote_subpath,self.conflict,self.commit_message,self.upload_workers],wrap=True,spacing=10),
                    self.confirm_overwrite,
                    self.status,
                    self.queue_panel,
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
                    ft.Row([
                        ft.OutlinedButton("比较本地与远程内容",icon=ft.Icons.COMPARE_ARROWS,on_click=self.sync_preview),
                        self.sync_upload_button,self.sync_download_button,
                    ],wrap=True),
                    self.sync_selection_summary,
                    self.sync_result_list,
                    self.preview_text
                ]))
        ])

    def on_download_conflict_change(self,e):
        self.confirm_download_overwrite.visible=self.download_conflict.value=="overwrite"
        self.save_preferences()
        if not self.confirm_download_overwrite.visible:
            self.confirm_download_overwrite.value=False
        self.page.update()

    async def pick_download_folder(self,e=None):
        try:
            selected=await self.file_picker.get_directory_path(dialog_title="选择远程图片保存目录")
            if selected:
                self.download_folder.value=selected
                self.save_preferences()
                self.status.value=f"下载目录已设置：{selected}"
                self.page.update()
        except Exception as ex:
            self.status.value=f"选择下载目录失败：{ex}"
            self.page.update()

    def on_conflict_change(self,e):
        self.confirm_overwrite.visible=self.conflict.value=="overwrite"
        self.save_preferences()
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


    def restore_preferences(self):
        """Restore non-secret desktop preferences saved in SQLite."""
        try:
            values=get_settings()
            controls=(
                ("download_folder",self.download_folder),
                ("download_conflict",self.download_conflict),
                ("download_workers",self.download_workers),
                ("upload_conflict",self.conflict),
                ("upload_workers",self.upload_workers),
                ("commit_message",self.commit_message),
                ("remote_subpath",self.remote_subpath),
            )
            for key,control in controls:
                if key in values:
                    control.value=values[key]
            self.confirm_download_overwrite.visible=self.download_conflict.value=="overwrite"
            self.confirm_overwrite.visible=self.conflict.value=="overwrite"
        except Exception as ex:
            self.status.value=f"设置读取失败，已使用默认设置：{ex}"

    def save_preferences(self,e=None):
        controls=(
            ("download_folder",self.download_folder),
            ("download_conflict",self.download_conflict),
            ("download_workers",self.download_workers),
            ("upload_conflict",self.conflict),
            ("upload_workers",self.upload_workers),
            ("commit_message",self.commit_message),
            ("remote_subpath",self.remote_subpath),
            ("local_folder",self.local_folder),
        )
        try:
            for key,control in controls:
                if control.value is not None:
                    set_setting(key,control.value)
        except Exception as ex:
            self.status.value=f"设置保存失败：{ex}"

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
        self.remote_items=[]
        self.remote_cache={}
        self.gallery.controls.clear()
        self.gallery.visible=False
        self.remote_empty.value="尚未读取远程图片。点击“读取远程图片”开始浏览。"
        self.remote_empty.visible=True
        self.remote_count.value=""
        self.sync_rows=[]
        self.sync_selected=set()
        self.sync_result_list.controls.clear()
        self.preview_text.value=""
        self.status.value="已切换仓库，请重新读取远程图片"
        self.page.update()

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
                ft.OutlinedButton("删除配置",icon=ft.Icons.DELETE,on_click=lambda e,row=r:self.confirm_remove_repo(row))]))))
        if self.page:self.page.update()

    def confirm_remove_repo(self,row):
        dialog=ft.AlertDialog(
            modal=True,
            title=ft.Text("删除仓库配置？"),
            content=ft.Text(
                f"确定删除“{row['name']}”吗？关联的历史任务和操作记录会保留，但该仓库的访问凭据也会被删除。"
            ),
            actions=[
                ft.TextButton("取消",on_click=lambda e:self.page.pop_dialog()),
                ft.Button("确认删除",icon=ft.Icons.DELETE,on_click=lambda e:self.remove_repo(row)),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.show_dialog(dialog)

    def remove_repo(self,row):
        self.page.pop_dialog()
        delete_repository(row["id"]);delete_token(row);self.refresh_repositories()
        self.status.value=f"已删除仓库配置：{row['name']}"
        self.page.update()

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
        self._local_preview_generation=getattr(self,"_local_preview_generation",0)+1
        self.local_files=unique
        self._local_preview_errors=[]
        self._local_preview_next=0
        self._local_preview_page_size=100
        self.local_gallery.visible=bool(unique)
        self.local_empty.visible=not bool(unique)
        self.local_gallery.controls=[]
        self.upload_button.disabled=not unique
        self.folder_upload_button.disabled=not (self.local_mode=="folder" and unique)
        self.local_summary.value=f"已选择 {len(unique)} 张图片"
        self.local_load_more.visible=False
        self.local_load_more.disabled=False
        self.page.update()
        await self.load_more_local_previews()

    def build_local_preview_card(self,path,thumbnail=None,error=None):
        if thumbnail:
            preview=ft.Image(src=str(thumbnail),width=160,height=108,fit=ft.BoxFit.CONTAIN)
        else:
            preview=ft.Icon(ft.Icons.BROKEN_IMAGE,color=ft.Colors.RED,size=36)
        details=(ft.Text(f"预览失败：{error}",size=10,color=ft.Colors.RED,max_lines=3)
                 if error else ft.Text(f"{path.stat().st_size:,} bytes",size=10,color=ft.Colors.GREY_600))
        return ft.Container(
            padding=8,border_radius=12,border=ft.Border.all(1,ft.Colors.OUTLINE_VARIANT),
            content=ft.Column(spacing=6,controls=[
                ft.Container(height=112,alignment=ft.Alignment.CENTER,content=preview),
                ft.Text(path.name,size=12,weight=ft.FontWeight.BOLD,max_lines=1,overflow=ft.TextOverflow.ELLIPSIS),
                details,
                ft.Row([ft.IconButton(ft.Icons.CLOSE,tooltip="从上传列表移除",
                    on_click=lambda e,p=path:self.remove_local_file(p))],alignment=ft.MainAxisAlignment.END)
            ])
        )

    async def load_more_local_previews(self,e=None):
        generation=getattr(self,"_local_preview_generation",0)
        start=self._local_preview_next
        end=min(start+self._local_preview_page_size,len(self.local_files))
        if start>=end:
            self.local_load_more.visible=False
            self.page.update()
            return
        self.local_load_more.disabled=True
        self.status.value=f"正在生成预览：{start+1}-{end} / {len(self.local_files)}"
        self.page.update()
        semaphore=asyncio.Semaphore(6)
        async def make_preview(path):
            async with semaphore:
                try:
                    return await asyncio.to_thread(
                        create_local_thumbnail,path,str(CACHE_DIR/"local")
                    )
                except Exception as exc:
                    return exc
        paths=self.local_files[start:end]
        results=await asyncio.gather(*(make_preview(path) for path in paths))
        if generation!=getattr(self,"_local_preview_generation",0):
            return
        for offset,(path,result) in enumerate(zip(paths,results),start=0):
            if isinstance(result,Exception):
                self._local_preview_errors.append(f"{path.name}: {result}")
                card=self.build_local_preview_card(path,error=str(result))
            else:
                card=self.build_local_preview_card(path,thumbnail=result)
            self.local_gallery.controls.append(card)
            if (offset+1)%20==0:
                self.page.update()
        self._local_preview_next=end
        self.local_load_more.visible=end<len(self.local_files)
        self.local_load_more.disabled=False
        self.local_load_more.text=f"加载更多（已显示 {end}/{len(self.local_files)}）" if end<len(self.local_files) else "已全部显示"
        self.status.value=f"本地图片已加入队列：{len(self.local_files)} 张；已显示预览 {end} 张"
        if self._local_preview_errors:
            self.status.value+=f"；其中 {len(self._local_preview_errors)} 张预览失败，但仍可尝试上传"
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
        self._local_preview_generation=getattr(self,"_local_preview_generation",0)+1
        self.local_files=[]
        self.local_gallery.visible=False
        self.local_empty.visible=True
        self.local_mode="files"
        self.local_root=None
        self.local_folder.value=""
        self.local_gallery.controls.clear()
        self.local_load_more.visible=False
        self.local_load_more.disabled=False
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
                "max_workers":int(self.upload_workers.value or "3"),
                "completed":{},
                "file_signatures":{
                    str(p.resolve()):{"size":p.stat().st_size,"mtime_ns":p.stat().st_mtime_ns}
                    for p in self.local_files
                }
            }
            self.save_preferences()
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
        progress_lock=Lock()
        # Resolve progress events in O(1) rather than scanning the remaining
        # file list for every callback (which becomes quadratic for large folders).
        remaining_lookup={}
        for item in remaining:
            relative_path=(item.relative_to(self.local_root).as_posix()
                           if self.local_root and item.is_relative_to(self.local_root) else item.name)
            remaining_lookup[relative_path]=item
            remaining_lookup[str(item)]=item
        overall_indexes={str(item.resolve()): index+1 for index,item in enumerate(paths)}
        persisted_checkpoint_count=0

        def progress_callback(index,total,path,state,message):
            nonlocal persisted_checkpoint_count
            matched=remaining_lookup.get(path)
            if matched is not None:
                overall_index=overall_indexes.get(str(matched.resolve()),index)
                if state in {"uploaded","skipped","failed","queued"}:
                    with progress_lock:
                        completed[str(matched.resolve())]={"state":state,"message":message}
                        persisted_checkpoint_count+=1
                        processed=sum(1 for value in completed.values()
                                      if value.get("state") in {"uploaded","skipped","failed"})
                        should_checkpoint=persisted_checkpoint_count % 5 == 0
                        checkpoint_payload=({**payload,"completed":dict(completed)}
                                            if should_checkpoint else None)
                    summary=f"已处理 {processed} 项"
                    # Snapshot under the progress lock so concurrent workers cannot
                    # mutate the completed map while JSON serialization is running.
                    if checkpoint_payload is not None:
                        update_upload_task(task_id,payload=checkpoint_payload,summary=summary)
                    else:
                        update_upload_task(task_id,summary=summary)
                loop.call_soon_threadsafe(self.update_upload_progress,overall_index,len(paths),str(matched),state,message)
            else:
                loop.call_soon_threadsafe(self.update_upload_progress,index,len(paths),path,state,message)
        try:
            results=await self.run_background(
                upload_paths,repo,self.token_for(repo),remaining,
                payload.get("conflict","skip"),payload.get("commit_message","GitNest image upload"),
                payload.get("remote_subpath",""),payload.get("relative_to"),
                progress_callback=progress_callback,control=control,
                max_workers=int(payload.get("max_workers",3)),
                expected_files=payload.get("file_signatures")
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
        state_labels={"queued":"等待执行","running":"正在执行","paused":"已暂停","completed":"已完成","failed":"失败","cancelled":"已取消"}
        for task in rows:
            state=task["status"]
            state_label=state_labels.get(state,state)
            can_resume=state in {"paused","failed","queued"}
            self.saved_tasks.controls.append(ft.Container(padding=8,border=ft.Border.all(1,ft.Colors.OUTLINE_VARIANT),
                border_radius=8,content=ft.Row([
                    ft.Column([ft.Text(f"任务 #{task['id']} · {state_label}",weight=ft.FontWeight.BOLD),
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
        self.upload_workers.value=str(payload.get("max_workers",3))
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
        labels={"uploading":"正在上传","uploaded":"已上传","skipped":"已跳过","failed":"失败","queued":"等待继续"}
        target=str(path)
        row=next((item for item in self.upload_queue_rows
                  if str(Path(item["path"]).resolve())==str(Path(target).resolve())),None)
        if row is not None:
            row["state"]=state
            row["message"]=message
            self.refresh_upload_queue()
        done=sum(1 for item in self.upload_queue_rows
                 if item["state"] in {"uploaded","skipped","failed"})
        self.upload_progress.value=(done/total) if total else 1
        self.status.value=f"上传进度 {done}/{total} · {labels.get(state,state)}：{Path(target).name}"
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
            self.remote_empty.visible=not bool(items)
            self.remote_empty.value="该仓库目录中没有图片。" if not items else "正在生成远程图片预览……"
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
        self.remote_empty.visible=not bool(image_items)
        if self.remote_items:
            self.remote_empty.value="没有匹配的图片，请调整搜索关键词或格式筛选。"
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

    def toggle_upload_queue(self,e=None):
        self.queue_expanded=not self.queue_expanded
        self.queue_body.visible=self.queue_expanded
        self.queue_toggle.icon=ft.Icons.EXPAND_LESS if self.queue_expanded else ft.Icons.EXPAND_MORE
        self.queue_toggle.tooltip="收起上传任务队列" if self.queue_expanded else "展开上传任务队列"
        self.page.update()

    def refresh_upload_queue(self):
        labels={"queued":"排队中","uploading":"正在上传","uploaded":"成功","skipped":"已跳过","failed":"失败"}
        colors={"queued":"#667085","uploading":"#2563EB","uploaded":"#15803D","skipped":"#B45309","failed":"#DC2626"}
        counts={key:sum(1 for row in self.upload_queue_rows if row["state"]==key) for key in labels}
        total=len(self.upload_queue_rows)
        self.queue_summary.value=(
            f"上传任务队列  ·  共 {total} 项  ·  "
            f"排队 {counts['queued']}  ·  上传中 {counts['uploading']}  ·  "
            f"成功 {counts['uploaded']}  ·  跳过 {counts['skipped']}  ·  失败 {counts['failed']}"
        )
        self.queue_list.controls=[]
        for row in self.upload_queue_rows:
            state=row.get("state","queued")
            name=Path(row["path"]).name
            message=row.get("message","")
            self.queue_list.controls.append(
                ft.Container(
                    padding=ft.Padding(8,5,8,5),
                    border_radius=8,
                    bgcolor="#FFFFFF",
                    border=ft.Border.all(1,"#EEF1F5"),
                    content=ft.Row([
                        ft.Container(width=7,height=7,border_radius=4,bgcolor=colors.get(state,"#667085")),
                        ft.Column([
                            ft.Text(name,size=12,weight=ft.FontWeight.W_600,
                                    max_lines=1,overflow=ft.TextOverflow.ELLIPSIS),
                            ft.Text(f"{labels.get(state,state)} · {message}" if message else labels.get(state,state),
                                    size=10,color=colors.get(state,"#667085"),
                                    max_lines=2,overflow=ft.TextOverflow.ELLIPSIS)
                        ],spacing=2,expand=True)
                    ],spacing=8)
                )
            )
        self.queue_panel.visible=bool(self.upload_queue_rows)
        self.queue_body.visible=self.queue_expanded and bool(self.upload_queue_rows)
        self.queue_toggle.icon=ft.Icons.EXPAND_LESS if self.queue_expanded else ft.Icons.EXPAND_MORE
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
            if not self.download_folder.value:raise ValueError("请先选择独立的下载目录")
            if self.download_conflict.value=="overwrite" and not self.confirm_download_overwrite.value:
                raise ValueError("覆盖模式会替换本地同名文件，请先勾选覆盖确认")
            repo=self.current_repo()
            result=await self.run_background(download_one,repo,self.token_for(repo),item.path,
                self.download_folder.value,self.download_conflict.value)
            if result is None:
                add_log(repo["id"],"download",item.path,"skipped","本地同名文件已存在，按策略跳过")
                self.status.value=f"已跳过：{item.name}（本地文件已存在）"
            else:
                add_log(repo["id"],"download",item.path,"success",str(result))
                self.status.value=f"下载成功：{result}"
        except Exception as ex:
            self.status.value=f"下载失败：{ex}"
        self.page.update()

    async def download_remote_all(self,e):
        try:
            if not self.download_folder.value:raise ValueError("请先选择独立的下载目录")
            self.save_preferences()
            if not self.remote_items:raise ValueError("请先读取远程图片")
            if self.download_conflict.value=="overwrite" and not self.confirm_download_overwrite.value:
                raise ValueError("覆盖模式会替换本地同名文件，请先勾选覆盖确认")
            repo=self.current_repo()
            results=await self.run_background(download_all,repo,self.token_for(repo),
                self.download_folder.value,self.remote_items,self.download_conflict.value,
                max_workers=int(self.download_workers.value or "4"))
            if results is None:return
            counts={"downloaded":0,"skipped":0,"failed":0}
            for path,state,msg in results:
                counts[state]=counts.get(state,0)+1
                add_log(repo["id"],"download",path,"success" if state=="downloaded" else state,msg)
            self.status.value=(f"批量下载完成：成功 {counts['downloaded']}，跳过 {counts['skipped']}，"
                               f"失败 {counts['failed']}")
        except Exception as ex:
            self.status.value=f"下载失败：{ex}"
        self.page.update()

    async def upload_local(self,e):
        if self.local_mode!="folder" or not self.local_root:
            self.status.value="请先选择本地图片目录"
            self.page.update()
            return
        await self.upload_selected(e)

    def update_sync_selection(self, path, checked):
        if checked:
            self.sync_selected.add(path)
        else:
            self.sync_selected.discard(path)
        selected=[row for row in self.sync_rows if row["path"] in self.sync_selected]
        uploads=sum(1 for row in selected if row["action"]=="upload")
        downloads=sum(1 for row in selected if row["action"]=="download")
        self.sync_selection_summary.value=f"已勾选 {len(selected)} 项：上传 {uploads}，下载 {downloads}（内容不同/比对失败的项目不会自动同步）"
        self.sync_upload_button.disabled=uploads==0
        self.sync_download_button.disabled=downloads==0
        self.page.update()

    async def sync_preview(self,e):
        try:
            if not self.local_folder.value:
                raise ValueError("请先选择本地目录")
            if not self.remote_items:
                raise ValueError("请先读取远程图片")
            repo=self.current_repo()
            rows=await self.run_background(compare_folders,repo,self.token_for(repo),self.local_folder.value,self.remote_items)
            if rows is None:
                return
            self.sync_rows=rows
            self.sync_selected=set()
            self.sync_result_list.controls=[]
            labels={"local_only":"仅本地 · 可上传","remote_only":"仅远程 · 可下载",
                    "same":"内容一致","different":"内容不同 · 需要人工确认","error":"比对失败 · 暂不可同步"}
            for row in rows:
                actionable=row["status"] in {"local_only","remote_only"}
                checkbox=ft.Checkbox(
                    value=False,disabled=not actionable,
                    on_change=lambda event,p=row["path"]:self.update_sync_selection(p,event.control.value)
                )
                details=f"本地：{row.get('local_size') if row.get('local_size') is not None else '-'} bytes  |  远程：{row.get('remote_size') if row.get('remote_size') is not None else '-'} bytes"
                if row.get("error"):
                    details+=f"  |  {row['error']}"
                self.sync_result_list.controls.append(
                    ft.Container(
                        padding=ft.Padding(8,5,8,5),
                        border=ft.Border.all(1,"#E7EBF2"),
                        border_radius=8,
                        content=ft.Row([
                            checkbox,
                            ft.Column([
                                ft.Text(f"{labels[row['status']]}  |  {row['path']}",weight=ft.FontWeight.W_500),
                                ft.Text(details,size=11,color=ft.Colors.GREY_600)
                            ],spacing=2,expand=True)
                        ],vertical_alignment=ft.CrossAxisAlignment.CENTER)
                    )
                )
            counts={key:sum(1 for row in rows if row["status"]==key) for key in labels}
            summary="比较完成："+"；".join(f"{labels[k]} {v}" for k,v in counts.items() if v)
            self.preview_text.value=summary if rows else "两端没有图片文件"
            self.sync_selection_summary.value="请勾选需要上传或下载的项目；内容不同的文件需先人工确认。"
            self.sync_upload_button.disabled=True
            self.sync_download_button.disabled=True
            self.status.value="差异分析完成：仅本地和仅远程项目可勾选执行"
        except Exception as ex:
            self.preview_text.value=f"比较失败：{ex}"
            self.status.value=f"同步比较失败：{ex}"
        self.page.update()

    async def sync_upload_selected(self,e=None):
        try:
            selected=[row for row in self.sync_rows
                      if row["path"] in self.sync_selected and row["action"]=="upload"]
            if not selected:
                raise ValueError("请先勾选仅本地的图片")
            if self.conflict.value=="overwrite" and not self.confirm_overwrite.value:
                raise ValueError("覆盖远程文件需要先勾选覆盖确认")
            root=Path(self.local_folder.value).expanduser().resolve()
            paths=[(root / row["path"]).resolve() for row in selected]
            if any(not path.is_relative_to(root) or not path.is_file() for path in paths):
                raise ValueError("部分本地文件已不存在或路径异常，请重新比较")
            self.local_root=root
            self.local_mode="folder"
            self.local_files=paths
            self.local_summary.value=f"同步待上传 {len(paths)} 张图片"
            self.page.update()
            await self.upload_selected(e)
            # Upload task completion is tracked by the existing persistent task center.
        except Exception as ex:
            self.status.value=f"同步上传失败：{ex}"
            self.page.update()

    async def sync_download_selected(self,e=None):
        try:
            selected=[row for row in self.sync_rows
                      if row["path"] in self.sync_selected and row["action"]=="download"]
            if not selected:
                raise ValueError("请先勾选仅远程的图片")
            if not self.download_folder.value:
                raise ValueError("请先设置独立的下载目录")
            if self.download_conflict.value=="overwrite" and not self.confirm_download_overwrite.value:
                raise ValueError("覆盖本地文件需要先勾选覆盖确认")
            selected_paths={row["path"] for row in selected}
            items=[item for item in self.remote_items
                   if any(item.path.endswith("/"+path) or item.path==path for path in selected_paths)]
            if len(items)!=len(selected):
                raise ValueError("远程文件列表已变化，请重新读取远程图片并比较")
            repo=self.current_repo()
            results=await self.run_background(download_all,repo,self.token_for(repo),
                self.download_folder.value,items,self.download_conflict.value,
                max_workers=int(self.download_workers.value or "4"))
            if results is None:
                return
            counts={"downloaded":0,"skipped":0,"failed":0}
            for path,state,message in results:
                counts[state]=counts.get(state,0)+1
                add_log(repo["id"],"sync_download",path,state,message)
            self.status.value=f"选中项下载完成：成功 {counts['downloaded']}，跳过 {counts['skipped']}，失败 {counts['failed']}"
            self.sync_selected.clear()
            self.update_sync_selection("",False)
        except Exception as ex:
            self.status.value=f"同步下载失败：{ex}"
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
