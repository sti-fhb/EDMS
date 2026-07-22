import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { Pagination } from "./Pagination"
import { renderWithProviders } from "../test/renderWithProviders"

describe("Pagination", () => {
  it("total 為 0 時不渲染", () => {
    const { container } = renderWithProviders(<Pagination page={1} total={0} onPageChange={() => {}} />)
    expect(container).toBeEmptyDOMElement()
  })

  it("點頁碼觸發 onPageChange", async () => {
    const user = userEvent.setup()
    const onPageChange = vi.fn()
    // total 25 / pageSize 10 → 3 頁
    renderWithProviders(<Pagination page={1} total={25} onPageChange={onPageChange} />)

    await user.click(screen.getByRole("button", { name: "Go to page 2" }))

    expect(onPageChange).toHaveBeenCalledWith(2)
  })

  it("切換每頁筆數時回傳新筆數並重置回第 1 頁", async () => {
    const user = userEvent.setup()
    const onPageChange = vi.fn()
    const onPageSizeChange = vi.fn()
    renderWithProviders(
      <Pagination
        page={3}
        total={100}
        pageSize={10}
        onPageChange={onPageChange}
        onPageSizeChange={onPageSizeChange}
      />,
    )

    await user.click(screen.getByLabelText("每頁筆數"))
    await user.click(await screen.findByRole("option", { name: "20" }))

    expect(onPageSizeChange).toHaveBeenCalledWith(20)
    expect(onPageChange).toHaveBeenCalledWith(1)
  })
})
