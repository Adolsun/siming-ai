import { Button, Modal } from 'antd'

export type CatalogingImpact = 'semantic' | 'style_only'

export function confirmChapterSave(): Promise<CatalogingImpact | null> {
  return new Promise((resolve) => {
    const dialog = Modal.confirm({
      title: '这次修改涉及剧情或设定吗？',
      content: '仅润色：只改措辞、句式或标点，保留现有建档状态。剧情有变化：改了事实、角色状态、设定、事件顺序或章节结构，保存后本章及后续旧档案需要重新建档。',
      okText: '剧情有变化并保存',
      cancelText: '返回编辑',
      autoFocusButton: 'cancel',
      maskClosable: false,
      footer: (_, { OkBtn, CancelBtn }) => (
        <div className="chapter-save-impact-actions">
          <CancelBtn />
          <Button onClick={() => { dialog.destroy(); resolve('style_only') }}>
            仅润色并保存
          </Button>
          <OkBtn />
        </div>
      ),
      onOk: () => resolve('semantic'),
      onCancel: () => resolve(null),
    })
  })
}
