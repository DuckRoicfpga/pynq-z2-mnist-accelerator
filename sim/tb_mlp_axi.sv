`timescale 1ns / 1ps
`include "params.vh"
`include "case_count.vh"

module tb_mlp_axi;
    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0;
    reg [15:0] awaddr = 0, araddr = 0;
    reg [2:0] awprot = 0, arprot = 0;
    reg awvalid = 0, wvalid = 0, bready = 0, arvalid = 0, rready = 0;
    reg [31:0] wdata = 0;
    reg [3:0] wstrb = 0;
    wire awready, wready, bvalid, arready, rvalid, irq;
    wire [1:0] bresp, rresp;
    wire [31:0] rdata;
    mlp_axi_lite dut (
        .s_axi_aclk(clk), .s_axi_aresetn(rst_n),
        .s_axi_awaddr(awaddr), .s_axi_awprot(awprot), .s_axi_awvalid(awvalid), .s_axi_awready(awready),
        .s_axi_wdata(wdata), .s_axi_wstrb(wstrb), .s_axi_wvalid(wvalid), .s_axi_wready(wready),
        .s_axi_bresp(bresp), .s_axi_bvalid(bvalid), .s_axi_bready(bready),
        .s_axi_araddr(araddr), .s_axi_arprot(arprot), .s_axi_arvalid(arvalid), .s_axi_arready(arready),
        .s_axi_rdata(rdata), .s_axi_rresp(rresp), .s_axi_rvalid(rvalid), .s_axi_rready(rready), .irq(irq)
    );
    reg [7:0] inputs [0:`CASE_COUNT*784-1];
    reg [7:0] expected_l1 [0:`CASE_COUNT*128-1];
    reg [7:0] expected_l2 [0:`CASE_COUNT*64-1];
    reg signed [31:0] expected_l3 [0:`CASE_COUNT*10-1];
    reg [7:0] expected_predictions [0:`CASE_COUNT-1];
    reg [31:0] rd, rd_parallel, packed_pixels;
    integer idx, word_idx, n, poll_count, fd;
    integer write_count = 0, read_count = 0;
    reg previous_b_stall = 0, previous_r_stall = 0;
    reg [1:0] saved_bresp, saved_rresp;
    reg [31:0] saved_rdata;

    // AXI response payload and VALID must stay stable while stalled.
    always @(posedge clk) begin
        if (!rst_n) begin
            previous_b_stall <= 0;
            previous_r_stall <= 0;
        end else begin
            if (previous_b_stall && (bvalid !== 1 || bresp !== saved_bresp))
                $fatal(1, "AXI B response changed under backpressure");
            if (previous_r_stall && (rvalid !== 1 || rresp !== saved_rresp || rdata !== saved_rdata))
                $fatal(1, "AXI R response changed under backpressure");
            previous_b_stall <= bvalid && !bready;
            previous_r_stall <= rvalid && !rready;
            saved_bresp <= bresp;
            saved_rresp <= rresp;
            saved_rdata <= rdata;
        end
    end

    task axi_write(input [15:0] addr, input [31:0] data,
                   input [3:0] strobe, input integer aw_delay,
                   input integer w_delay, input integer response_stall,
                   input [1:0] expected_resp);
        begin
            fork
                begin
                    repeat (aw_delay) @(negedge clk);
                    @(negedge clk);
                    awaddr = addr;
                    awvalid = 1;
                    do @(posedge clk); while (!awready);
                    @(negedge clk);
                    awvalid = 0;
                end
                begin
                    repeat (w_delay) @(negedge clk);
                    @(negedge clk);
                    wdata = data;
                    wstrb = strobe;
                    wvalid = 1;
                    do @(posedge clk); while (!wready);
                    @(negedge clk);
                    wvalid = 0;
                end
            join
            wait (bvalid);
            #1;
            if (bresp !== expected_resp)
                $fatal(1, "BRESP mismatch address=%h got=%h expected=%h", addr, bresp, expected_resp);
            repeat (response_stall) @(negedge clk);
            @(negedge clk);
            bready = 1;
            @(posedge clk);
            @(negedge clk);
            bready = 0;
            write_count = write_count + 1;
        end
    endtask

    task axi_read(input [15:0] addr, input integer response_stall,
                  input [1:0] expected_resp, output [31:0] data);
        begin
            @(negedge clk);
            araddr = addr;
            arvalid = 1;
            do @(posedge clk); while (!arready);
            @(negedge clk);
            arvalid = 0;
            wait (rvalid);
            #1;
            if (rresp !== expected_resp)
                $fatal(1, "RRESP mismatch address=%h got=%h expected=%h", addr, rresp, expected_resp);
            data = rdata;
            repeat (response_stall) @(negedge clk);
            @(negedge clk);
            rready = 1;
            @(posedge clk);
            @(negedge clk);
            rready = 0;
            read_count = read_count + 1;
        end
    endtask

    task load_case(input integer case_number);
        integer p;
        reg [31:0] packed_word;
        begin
            for (p = 0; p < 196; p = p + 1) begin
                packed_word = {inputs[case_number*784 + p*4 + 3], inputs[case_number*784 + p*4 + 2],
                               inputs[case_number*784 + p*4 + 1], inputs[case_number*784 + p*4]};
                // Covers simultaneous, AW-first and W-first handshakes.
                axi_write(16'h1000 + p*4, packed_word, 4'hF, p%3, (p+1)%3, p%4, 0);
            end
            axi_read(16'h001C, 2, 0, rd);
            if (rd !== 784) $fatal(1, "Incorrect loaded pixel count: %0d", rd);
        end
    endtask

    initial begin
        repeat (20000000) @(posedge clk);
        $fatal(1, "AXI test global timeout");
    end

    initial begin
        $readmemh("inputs.mem", inputs);
        $readmemh("expected_l1.mem", expected_l1);
        $readmemh("expected_l2.mem", expected_l2);
        $readmemh("expected_l3.mem", expected_l3);
        $readmemh("expected_predictions.mem", expected_predictions);
        fd = $fopen("axi_results.csv", "w");
        if (!fd) $fatal(1, "Cannot write AXI result CSV");
        $fdisplay(fd, "case,prediction,cycles");
        repeat (5) @(negedge clk);
        rst_n = 1;

        // Reset with an address captured but without its write data.
        @(negedge clk);
        awaddr = 16'h1000;
        awvalid = 1;
        do @(posedge clk); while (!awready);
        @(negedge clk);
        awvalid = 0;
        rst_n = 0;
        repeat (5) @(negedge clk);
        if (bvalid !== 0) $fatal(1, "Stale write response across reset");
        rst_n = 1;

        axi_read(16'h0018, 5, 0, rd);
        if (rd !== 32'h4D4C5031) $fatal(1, "Incorrect accelerator ID");
        axi_read(16'h0010, 0, 0, rd);
        if (rd !== 100000000) $fatal(1, "Incorrect clock register");
        axi_write(0, 1, 4'hF, 0, 5, 5, 2'b10); // incomplete image
        axi_read(16'h0024, 0, 0, rd);
        if (rd !== 2) $fatal(1, "Incomplete image must report error 2");
        axi_write(16'h0018, 0, 4'hF, 5, 0, 3, 2'b10); // read-only
        axi_write(16'h0030, 0, 4'hF, 0, 0, 0, 2'b10); // unmapped
        axi_write(16'h1001, 0, 4'hF, 0, 0, 0, 2'b10); // misaligned
        axi_write(16'h1310, 0, 4'hF, 0, 0, 0, 2'b10); // past last pixel
        axi_read(16'h1000, 4, 2'b10, rd); // pixel window is write-only
        axi_read(16'h0001, 1, 2'b10, rd); // misaligned read
        axi_write(0, 2, 4'hF, 0, 0, 0, 0);

        // WSTRB selects bytes and duplicate writes must not inflate loaded_count.
        axi_write(16'h1000, 32'hAABBCCDD, 4'b0101, 4, 0, 2, 0);
        axi_read(16'h001C, 0, 0, rd);
        if (rd !== 2) $fatal(1, "Partial WSTRB must initialize two pixels");
        axi_write(16'h1000, 32'hAABBCCDD, 4'b1010, 0, 4, 2, 0);
        axi_write(16'h1000, 32'hAABBCCDD, 4'hF, 0, 0, 2, 0);
        axi_write(16'h1004, 32'hFFFFFFFF, 4'h0, 0, 0, 2, 0);
        axi_read(16'h001C, 0, 0, rd);
        if (rd !== 4) $fatal(1, "Repeated/no-strobe writes changed initialized count");
        if (dut.core.input_mem[0] !== 8'hDD || dut.core.input_mem[1] !== 8'hCC ||
            dut.core.input_mem[2] !== 8'hBB || dut.core.input_mem[3] !== 8'hAA)
            $fatal(1, "Pixel byte ordering/strobes incorrect");
        axi_write(0, 4, 4'h0, 0, 0, 0, 0); // no-strobe reset must do nothing
        axi_read(16'h001C, 0, 0, rd);
        if (rd !== 4) $fatal(1, "Control ignored WSTRB");

        // A stalled read must not block an independent write channel.
        fork
            axi_read(16'h0018, 12, 0, rd_parallel);
            axi_write(16'h0028, 1, 4'h1, 0, 3, 4, 0);
        join
        if (rd_parallel !== 32'h4D4C5031) $fatal(1, "Concurrent read/write failed");

        load_case(0);
        axi_write(0, 1, 4'hF, 0, 0, 0, 0);
        repeat (30) @(negedge clk);
        axi_write(0, 4, 4'hF, 0, 0, 0, 0); // abort active work
        repeat (10) @(negedge clk);
        axi_read(4, 0, 0, rd);
        if (rd !== 0) $fatal(1, "Soft reset must clear status and loaded pixels");
        if (dut.core_state !== 0) $fatal(1, "Core did not reset synchronously");
        $display("PASS: AXI split channels, backpressure, strobes, errors, concurrent R/W, reset and abort");

        for (idx = 0; idx < `CASE_COUNT; idx = idx + 1) begin
            load_case(idx);
            axi_write(0, 1, 4'h1, idx%3, (idx+2)%3, idx%4, 0);
            axi_read(4, 2, 0, rd);
            if (rd[0] !== 1 || rd[1] !== 0) $fatal(1, "START did not set BUSY / clear DONE");
            if (idx == 0) begin
                axi_write(0, 1, 4'h1, 0, 0, 2, 2'b10);
                axi_write(16'h1000, 32'hFFFFFFFF, 4'hF, 2, 0, 3, 2'b10);
            end
            // Sparse polling, with read response backpressure during computation.
            poll_count = 0;
            while (!rd[1] && poll_count < 250) begin
                repeat (500) @(negedge clk);
                axi_read(4, poll_count%3, 0, rd);
                poll_count = poll_count + 1;
            end
            if (!rd[1] || rd[0]) $fatal(1, "Inference timeout or BUSY stuck, case=%0d", idx);
            if (irq !== 1) $fatal(1, "DONE interrupt not asserted");
            axi_read(8, 5, 0, rd);
            if (rd !== {24'd0, expected_predictions[idx]})
                $fatal(1, "AXI prediction mismatch case=%0d got=%0d expected=%0d", idx, rd, expected_predictions[idx]);
            for (n = 0; n < 128; n = n + 1)
                if (dut.core.l1_out[n] !== expected_l1[idx*128+n]) $fatal(1, "AXI L1 mismatch");
            for (n = 0; n < 64; n = n + 1)
                if (dut.core.l2_out[n] !== expected_l2[idx*64+n]) $fatal(1, "AXI L2 mismatch");
            for (n = 0; n < 10; n = n + 1)
                if (dut.core.l3_out[n] !== expected_l3[idx*10+n]) $fatal(1, "AXI L3 mismatch");
            axi_read(16'h000C, 1, 0, rd);
            if (rd !== 110208) $fatal(1, "Cycle counter mismatch got=%0d", rd);
            $fdisplay(fd, "%0d,%0d,%0d", idx, expected_predictions[idx], rd);
            repeat (5) @(negedge clk);
            axi_read(4, 0, 0, rd);
            if (!rd[1]) $fatal(1, "DONE must remain sticky until cleared");
            axi_write(0, 2, 4'h1, 0, 0, 3, 0);
            if (irq !== 0) $fatal(1, "IRQ must clear after acknowledging DONE");
            if (idx < 10 || idx%10 == 9)
                $display("PASS AXI case=%0d result=%0d cycles=110208", idx, expected_predictions[idx]);
        end
        $fclose(fd);
        $display("AXI REGRESSION PASS: %0d/%0d cases, writes=%0d reads=%0d", `CASE_COUNT, `CASE_COUNT, write_count, read_count);
        $finish;
    end
endmodule
