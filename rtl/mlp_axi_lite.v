`timescale 1ns / 1ps

// AXI4-Lite slave: independent AW/W capture, one outstanding write/read,
// response backpressure, byte strobes, sticky completion and interrupt.
// Pixel window 0x1000..0x130F: 196 little-endian words, four UINT8 pixels/word.
module mlp_axi_lite #(
    parameter integer CLOCK_HZ = 100000000
) (
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 s_axi_aclk CLK",
       X_INTERFACE_PARAMETER = "XIL_INTERFACENAME s_axi_aclk, ASSOCIATED_BUSIF S_AXI, ASSOCIATED_RESET s_axi_aresetn" *)
    input wire s_axi_aclk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 s_axi_aresetn RST",
       X_INTERFACE_PARAMETER = "XIL_INTERFACENAME s_axi_aresetn, POLARITY ACTIVE_LOW" *)
    input wire s_axi_aresetn,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI AWADDR",
       X_INTERFACE_PARAMETER = "XIL_INTERFACENAME S_AXI, PROTOCOL AXI4LITE, DATA_WIDTH 32, ADDR_WIDTH 16" *)
    input wire [15:0] s_axi_awaddr,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI AWPROT" *)
    input wire [2:0] s_axi_awprot,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI AWVALID" *)
    input wire s_axi_awvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI AWREADY" *)
    output wire s_axi_awready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI WDATA" *)
    input wire [31:0] s_axi_wdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI WSTRB" *)
    input wire [3:0] s_axi_wstrb,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI WVALID" *)
    input wire s_axi_wvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI WREADY" *)
    output wire s_axi_wready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI BRESP" *)
    output reg [1:0] s_axi_bresp,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI BVALID" *)
    output reg s_axi_bvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI BREADY" *)
    input wire s_axi_bready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI ARADDR" *)
    input wire [15:0] s_axi_araddr,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI ARPROT" *)
    input wire [2:0] s_axi_arprot,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI ARVALID" *)
    input wire s_axi_arvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI ARREADY" *)
    output wire s_axi_arready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI RDATA" *)
    output reg [31:0] s_axi_rdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI RRESP" *)
    output reg [1:0] s_axi_rresp,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI RVALID" *)
    output reg s_axi_rvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI RREADY" *)
    input wire s_axi_rready,
    (* X_INTERFACE_INFO = "xilinx.com:signal:interrupt:1.0 irq INTERRUPT",
       X_INTERFACE_PARAMETER = "XIL_INTERFACENAME irq, SENSITIVITY LEVEL_HIGH" *)
    output wire irq
);
    localparam [1:0] OKAY = 2'b00, SLVERR = 2'b10;
    localparam [7:0] ERR_BUSY = 1, ERR_INCOMPLETE = 2,
                     ERR_ADDRESS = 3, ERR_READ_ONLY = 4;
    reg aw_pending, w_pending;
    reg [15:0] awaddr_hold;
    reg [31:0] wdata_hold;
    reg [3:0] wstrb_hold;
    reg pixel_write_active;
    reg [1:0] pixel_byte;
    reg [9:0] pixel_base;
    reg [783:0] loaded_mask;
    reg [9:0] loaded_count;
    reg busy, done_sticky, error_sticky, irq_enable;
    reg [7:0] error_code;
    reg [31:0] cycle_live, cycle_count;
    reg [3:0] result_reg;
    reg [2:0] soft_reset_count;
    reg core_start, core_pixel_wr;
    reg [9:0] core_pixel_addr;
    reg [7:0] core_pixel_data;
    wire core_done;
    wire [3:0] core_result;
    wire [2:0] core_state;
    wire [1:0] core_layer;
    wire [7:0] core_neuron;
    wire core_rst_n = s_axi_aresetn && (soft_reset_count == 0);
    wire device_busy = busy || (soft_reset_count != 0);
    wire image_ready = (loaded_count == 784);
    wire [9:0] next_pixel = pixel_base + {8'd0, pixel_byte};

    assign s_axi_awready = s_axi_aresetn && !aw_pending &&
        !s_axi_bvalid && !pixel_write_active && soft_reset_count == 0;
    assign s_axi_wready = s_axi_aresetn && !w_pending &&
        !s_axi_bvalid && !pixel_write_active && soft_reset_count == 0;
    assign s_axi_arready = s_axi_aresetn && !s_axi_rvalid;
    assign irq = irq_enable && done_sticky;

    mlp_accelerator core (
        .clk(s_axi_aclk), .rst_n(core_rst_n),
        .pixel_addr(core_pixel_addr), .pixel_data(core_pixel_data),
        .pixel_wr(core_pixel_wr), .start(core_start),
        .result(core_result), .done(core_done),
        .dbg_state(core_state), .dbg_layer(core_layer), .dbg_neuron(core_neuron)
    );

    task reject_write;
        input [7:0] code;
        begin
            s_axi_bvalid <= 1'b1;
            s_axi_bresp <= SLVERR;
            error_sticky <= 1'b1;
            error_code <= code;
        end
    endtask

    always @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            aw_pending <= 0;
            w_pending <= 0;
            awaddr_hold <= 0;
            wdata_hold <= 0;
            wstrb_hold <= 0;
            s_axi_bvalid <= 0;
            s_axi_bresp <= OKAY;
            s_axi_rvalid <= 0;
            s_axi_rresp <= OKAY;
            s_axi_rdata <= 0;
            pixel_write_active <= 0;
            pixel_byte <= 0;
            pixel_base <= 0;
            loaded_mask <= 0;
            loaded_count <= 0;
            busy <= 0;
            done_sticky <= 0;
            error_sticky <= 0;
            error_code <= 0;
            irq_enable <= 0;
            result_reg <= 0;
            cycle_live <= 0;
            cycle_count <= 0;
            soft_reset_count <= 0;
            core_start <= 0;
            core_pixel_wr <= 0;
            core_pixel_addr <= 0;
            core_pixel_data <= 0;
        end else begin
            core_start <= 0;
            core_pixel_wr <= 0;
            if (soft_reset_count != 0)
                soft_reset_count <= soft_reset_count - 1'b1;
            if (s_axi_bvalid && s_axi_bready)
                s_axi_bvalid <= 0;
            if (s_axi_rvalid && s_axi_rready)
                s_axi_rvalid <= 0;

            if (busy) begin
                if (core_done) begin
                    busy <= 0;
                    done_sticky <= 1;
                    result_reg <= core_result;
                    cycle_count <= cycle_live;
                end else if (core_start) begin
                    cycle_live <= 0;
                end else begin
                    cycle_live <= cycle_live + 1'b1;
                end
            end

            if (s_axi_awvalid && s_axi_awready) begin
                awaddr_hold <= s_axi_awaddr;
                aw_pending <= 1;
            end
            if (s_axi_wvalid && s_axi_wready) begin
                wdata_hold <= s_axi_wdata;
                wstrb_hold <= s_axi_wstrb;
                w_pending <= 1;
            end

            if (pixel_write_active) begin
                if (wstrb_hold[pixel_byte]) begin
                    core_pixel_addr <= next_pixel;
                    core_pixel_data <= wdata_hold >> (pixel_byte * 8);
                    core_pixel_wr <= 1;
                    if (!loaded_mask[next_pixel]) begin
                        loaded_mask[next_pixel] <= 1;
                        loaded_count <= loaded_count + 1'b1;
                    end
                end
                if (pixel_byte == 3) begin
                    pixel_write_active <= 0;
                    s_axi_bvalid <= 1;
                    s_axi_bresp <= OKAY;
                end else begin
                    pixel_byte <= pixel_byte + 1'b1;
                end
            end else if (aw_pending && w_pending && !s_axi_bvalid) begin
                aw_pending <= 0;
                w_pending <= 0;
                s_axi_bresp <= OKAY;
                if (awaddr_hold[1:0] != 0) begin
                    reject_write(ERR_ADDRESS);
                end else if (awaddr_hold >= 16'h1000 && awaddr_hold <= 16'h130C) begin
                    if (device_busy)
                        reject_write(ERR_BUSY);
                    else begin
                        pixel_base <= awaddr_hold[9:0];
                        pixel_byte <= 0;
                        pixel_write_active <= 1;
                    end
                end else begin
                    s_axi_bvalid <= 1;
                    case (awaddr_hold)
                        16'h0000: begin // CONTROL: pulse bits START, CLEAR, RESET
                            if (wstrb_hold[0]) begin
                                if (wdata_hold[2]) begin
                                    soft_reset_count <= 4;
                                    busy <= 0;
                                    done_sticky <= 0;
                                    error_sticky <= 0;
                                    error_code <= 0;
                                    loaded_mask <= 0;
                                    loaded_count <= 0;
                                    result_reg <= 0;
                                    cycle_live <= 0;
                                    cycle_count <= 0;
                                end else begin
                                    if (wdata_hold[1]) begin
                                        done_sticky <= 0;
                                        error_sticky <= 0;
                                        error_code <= 0;
                                    end
                                    if (wdata_hold[0]) begin
                                        if (device_busy)
                                            reject_write(ERR_BUSY);
                                        else if (!image_ready)
                                            reject_write(ERR_INCOMPLETE);
                                        else begin
                                            core_start <= 1;
                                            busy <= 1;
                                            done_sticky <= 0;
                                            error_sticky <= 0;
                                            error_code <= 0;
                                            cycle_live <= 0;
                                            cycle_count <= 0;
                                        end
                                    end
                                end
                            end
                        end
                        16'h0028: begin // IRQ_ENABLE bit 0
                            if (wstrb_hold[0]) irq_enable <= wdata_hold[0];
                        end
                        16'h0004, 16'h0008, 16'h000C, 16'h0010,
                        16'h0014, 16'h0018, 16'h001C, 16'h0020,
                        16'h0024: reject_write(ERR_READ_ONLY);
                        default: reject_write(ERR_ADDRESS);
                    endcase
                end
            end

            if (s_axi_arvalid && s_axi_arready) begin
                s_axi_rvalid <= 1;
                s_axi_rresp <= OKAY;
                s_axi_rdata <= 0;
                if (s_axi_araddr[1:0] != 0) begin
                    s_axi_rresp <= SLVERR;
                end else begin
                    case (s_axi_araddr)
                        16'h0000: s_axi_rdata <= 0;
                        16'h0004: s_axi_rdata <= {28'd0, image_ready, error_sticky, done_sticky, device_busy};
                        16'h0008: s_axi_rdata <= {28'd0, result_reg};
                        16'h000C: s_axi_rdata <= cycle_count;
                        16'h0010: s_axi_rdata <= CLOCK_HZ;
                        16'h0014: s_axi_rdata <= 784;
                        16'h0018: s_axi_rdata <= 32'h4D4C5031; // ASCII MLP1
                        16'h001C: s_axi_rdata <= {22'd0, loaded_count};
                        16'h0020: s_axi_rdata <= {8'd0, core_neuron, 6'd0, core_layer, 5'd0, core_state};
                        16'h0024: s_axi_rdata <= {24'd0, error_code};
                        16'h0028: s_axi_rdata <= {31'd0, irq_enable};
                        default: s_axi_rresp <= SLVERR; // pixels are write-only
                    endcase
                end
            end
        end
    end
endmodule
