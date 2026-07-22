import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { CartButton } from "./CartButton";

describe("CartButton", () => {
  it("displays the current item count (scenario 21)", () => {
    render(<CartButton itemCount={3} onClick={() => {}} />);
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByLabelText("3 items in cart")).toBeInTheDocument();
  });

  it("uses singular wording for exactly one item", () => {
    render(<CartButton itemCount={1} onClick={() => {}} />);
    expect(screen.getByLabelText("1 item in cart")).toBeInTheDocument();
  });

  it("shows zero for an empty cart, never a blank or missing count", () => {
    render(<CartButton itemCount={0} onClick={() => {}} />);
    expect(screen.getByText("0")).toBeInTheDocument();
  });

  it("calls onClick when pressed, to open the cart drawer", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<CartButton itemCount={0} onClick={onClick} />);
    await user.click(screen.getByRole("button"));
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
