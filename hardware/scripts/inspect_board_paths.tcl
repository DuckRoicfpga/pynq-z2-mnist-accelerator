set script_dir [file dirname [file normalize [info script]]]
set root_dir [file dirname [file dirname $script_dir]]
set repo [file join $root_dir hardware board_files]
set_param board.repoPaths [list $repo]
open_project [file join $root_dir hardware build mnist_pynq_z2 mnist_pynq_z2.xpr]
puts "REPO_BEFORE=[get_property board_part_repo_paths [current_project]]"
catch {set_property board_part_repo_paths [list [list $repo]] [current_project]} e
puts "REPO_SET_RESULT=$e"
puts "REPO_AFTER=[get_property board_part_repo_paths [current_project]]"
open_bd_design [get_files */mnist_system.bd]
set ps [get_bd_cells processing_system7_0]
catch {set_property CONFIG.PCW_M_AXI_GP0_FREQMHZ.VALUE_SRC DEFAULT $ps} e
puts "SOURCE_SET_RESULT=$e"
validate_bd_design
puts "GP_FREQ=[get_property CONFIG.PCW_M_AXI_GP0_FREQMHZ $ps]"
puts "GP_SOURCE=[get_property CONFIG.PCW_M_AXI_GP0_FREQMHZ.VALUE_SRC $ps]"
exit
