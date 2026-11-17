# fengniao_downloader
某老牌摄影网站的摄影作品下载脚本
 用法

  py -3 fengniao_download.py <帖子URL或tid> [--out 目录] [--pages N]

  几个例子：
  # 单个帖子
  py -3 fengniao_download.py https://bbs.fengniao.com/forum/12127185.html

  # 直接给帖子 id
  py -3 fengniao_download.py 12127185

  # 一次下多个帖子
  py -3 fengniao_download.py 12127185 12127199 --out D:/photos

  # 多页帖子（自动检测不到时手动指定）
  py -3 fengniao_download.py 12127185 --pages 3

  它自动做了什么

  - 自动分类：读取每张图的标签（人像/风光/生态…），按类别建文件夹
  - 自动命名：文件夹用「帖子标题_tid」命名，图按顺序编 01.jpg、02.jpg…
  - 去重：同一张图出现在多个楼层/入口时只下一次
  - 断点续传：已下载的文件会跳过，重复运行不重复下
  - 只下原图：抓的是网页"下载"按钮对应的 downloadPic（非缩略图）

  实际输出效果：
  fengniaowang/
  └── 人像/
      └── 【有图】人像（2026年11月8日 第二部分 ）_12127185/
          ├── 01.jpg  (2080×3089)
          ├── 02.jpg
          └── ...
