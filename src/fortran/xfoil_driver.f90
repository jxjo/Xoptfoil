!  This file is part of XOPTFOIL.

!  XOPTFOIL is free software: you can redistribute it and/or modify
!  it under the terms of the GNU General Public License as published by
!  the Free Software Foundation, either version 3 of the License, or
!  (at your option) any later version.

!  XOPTFOIL is distributed in the hope that it will be useful,
!  but WITHOUT ANY WARRANTY; without even the implied warranty of
!  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
!  GNU General Public License for more details.

!  You should have received a copy of the GNU General Public License
!  along with XOPTFOIL.  If not, see <http://www.gnu.org/licenses/>.

!  Copyright (C) 2017-2019 Daniel Prosser

module xfoil_driver

! Contains subroutines to use XFoil to analyze an airfoil

  implicit none


  type re_type 
    double precision :: number            ! Reynolds Number
    integer          :: type              ! Type 1 or 2 (fixed lift)
  end type re_type

  ! Hold result of xfoil boundary layer (BL) infos of an op_pooint #exp-bubble

  type bubble_type      
    logical          :: found             ! a bubble was detected           
    double precision :: xstart            ! start of separation: CF (shear stress) < 0
    double precision :: xend              ! end   of separation: CF (shear stress) > 0
  end type bubble_type                              

  ! defines an op_point for xfoil calculation

  type op_point_specification_type                              
    logical          :: spec_cl           ! op based on alpha or cl
    double precision :: value             ! base value of cl or alpha
    double precision :: weighting         ! weighting within objective function
    double precision :: scale_factor      ! scale for objective function
    type (re_type)   :: re, ma            ! Reynolds and Mach 
    double precision :: ncrit             ! xfoil ncrit
    character(15)    :: optimization_type ! eg 'min-drag'
    double precision :: target_value      ! target value to achieve
  end type op_point_specification_type

! Hold result of xfoil aero calculation of an op_pooint

  type op_point_result_type                              
    logical :: converged                  ! did xfoil converge? 
    double precision :: cl                ! lift coef.  - see also spec_cl
    double precision :: alpha             ! alpha (aoa) - see also spec_cl
    double precision :: cd                ! drag coef.  
    double precision :: cm                ! moment coef. 
    double precision :: xtrt              ! point of transition - top side 
    double precision :: xtrb              ! point of transition - bottom side 
    type (bubble_type) :: bubblet, bubbleb! bubble info - top and bottom #exp-bubble
  end type op_point_result_type                              


! defines xfoils calculation environment

  type xfoil_options_type
    double precision :: ncrit             ! Critical ampl. ratio
    double precision :: xtript, xtripb    ! forced trip locations
    logical :: viscous_mode               ! do viscous calculation           
    logical :: silent_mode                ! Toggle xfoil screen write
    logical :: repanel                    ! do re-paneling (PANGEN) before xfoil aero calcs 
    logical :: show_details               ! show some user entertainment 
    integer :: maxit                      ! max. iterations for BL calcs
    double precision :: vaccel            ! xfoil BL convergence accelerator
    logical :: fix_unconverged            ! try to fix unconverged pts.
    logical :: exit_if_unconverged        ! exit die op point loop if a point is unconverged
    logical :: reinitialize               ! reinitialize BLs per op_point
  end type xfoil_options_type


  type xfoil_geom_options_type   
    integer :: npan                       ! number of panels 
    double precision :: cvpar, cterat, ctrrat, xsref1, xsref2, xpref1, xpref2
  end type xfoil_geom_options_type


! result statistics for drag(lift) outlier detetction 

  type value_statistics_type   
    logical :: no_check                ! deactivate detection e.g. when flaps are set
    integer :: nvalue                  ! total numer of values tested
    double precision :: minval         ! the smallest value up to now 
    double precision :: maxval         ! the biggest value up to now 
    double precision :: meanval        ! the average value up to now 

  end type value_statistics_type

  type (value_statistics_type), dimension(:), allocatable, private :: drag_statistics

  contains


!=============================================================================
!
! Core routine to run xfoil calculation for each operating points
!      returns Cl, Cd, Cm, ... for an airfoil
!
!=============================================================================

subroutine run_op_points (foil, geom_options, xfoil_options,         &
                          use_flap, flap_spec, flap_degrees, &
                          op_points_spec, op_points_result)

  use xfoil_inc    
  use vardef,    only : airfoil_type
  use vardef,    only : flap_spec_type
  use os_util

  type(airfoil_type), intent(in)            :: foil
  type(xfoil_geom_options_type), intent(in) :: geom_options
  type(xfoil_options_type),      intent(in) :: xfoil_options
  type(flap_spec_type),          intent(in) :: flap_spec
  type(op_point_specification_type), dimension(:), intent(in)  :: op_points_spec
  type(op_point_result_type), dimension(:), allocatable, intent(out) :: op_points_result

  double precision, dimension(:), intent(in) :: flap_degrees
  logical, intent(in) :: use_flap


  integer :: i, noppoint
  integer :: iretry, nretry
  double precision :: prev_op_delta, op_delta, prev_flap_degree, prev_op_spec_value
  logical:: point_fixed, show_details, flap_changed, prev_op_spec_cl
  type(op_point_specification_type) :: op_spec, tmp_op_spec
  type(op_point_result_type)        :: op


  noppoint = size(op_points_spec,1)  

! Sanity checks

  if (.not. allocated(AIJ)) then
    write(*,*) "Error: xfoil is not initialized!  Call xfoil_init() first."
    stop
  end if
  if (noppoint == 0) then 
    write(*,*) "Error in xfoil_driver: No operating points"
    stop
  end if

! Init variables

  
  allocate (op_points_result(noppoint))

  prev_op_delta   = 0d0
  prev_op_spec_cl = op_points_spec(1)%spec_cl
  flap_changed = .false.
  prev_flap_degree = flap_degrees (1) 
  show_details = xfoil_options%show_details


! init statistics for out lier detection the first time and when polar changes
  if (.not. allocated(drag_statistics)) then
    call init_statistics (noppoint, drag_statistics)
  else if (size(drag_statistics) /= noppoint) then 
    call init_statistics (noppoint, drag_statistics)
  end if


! Set default Xfoil parameters 
  call xfoil_defaults(xfoil_options)

! Set paneling options
  call xfoil_set_paneling(geom_options)

  if (show_details) then 
    write (*,'(7x,A)',advance = 'no') 'Xfoil  '
    if (xfoil_options%repanel)      write (*,'(A)',advance = 'no') 'repanel '
    if (xfoil_options%reinitialize) write (*,'(A)',advance = 'no') 'init_BL '
  end if


! Run xfoil for requested operating points -----------------------------------
!
! Rules for initialization of xfoil boundary layer - xfoil_init_BL 
!
!   xfoil_options%reinitialize = 
!   .true.    init will bed one before *every* xfoil calculation 
!   .false.   init will be done only
!             - at the first op_point
!             - when the flap angle is changed (new foil is set)
!             - when a point didn't converge
!             - when the direction of alpha or cl changes along op points

  do i = 1, noppoint

    op_spec = op_points_spec(i)

!   print newline if output gets too long
    if (show_details .and.( mod(i,80) == 0)) write (*,'(/,7x,A)',advance = 'no') '       '

!   if flpas are activated, check if the angle has changed to reinit foil

    if(use_flap .and. (flap_degrees(i) /= prev_flap_degree)) then
      flap_changed = .true.
      prev_flap_degree = flap_degrees(i)
    else
      flap_changed = .false.
    end if 

!   set airfoil, apply flap deflection, init BL if needed
    if (flap_changed .or. (i == 1)) then

      ! set airfoil into xfoil buffer
      call xfoil_set_airfoil(foil)              ! "restore" current airfoil

      ! apply flap only if set to non zero degrees
      if (flap_changed) then
        call xfoil_apply_flap_deflection(flap_spec, flap_degrees(i))
      end if     

      ! repanel geometry only if requested...
      if (xfoil_options%repanel) call PANGEN(.not. SILENT_MODE)
      ! In case of flaps (or first op) always init boundary layer 
      call xfoil_init_BL (show_details)

    else
      ! Init BL always if set in parameters 
      if (xfoil_options%reinitialize) then 
        call xfoil_init_BL (.false.)
      else
        if (op_spec%spec_cl .neqv. prev_op_spec_cl) then  ! init if op_mode changed
          call xfoil_init_BL (show_details)
          prev_op_delta = 0d0
        else                                    ! Init BL if the direction of alpha or cl changes 
          op_delta = op_spec%value - prev_op_spec_value
          if ((prev_op_delta * op_delta) < 0d0) then 
            call xfoil_init_BL (show_details)
            prev_op_delta = 0d0
          else
            prev_op_delta = op_delta
          end if 
        end if
      end if
    end if

    prev_op_spec_value = op_spec%value
    prev_op_spec_cl    = op_spec%spec_cl

!   Now finally run xfoil at op_point
    call run_op_point (op_spec, &
                      xfoil_options%viscous_mode, xfoil_options%maxit, show_details, & 
                      op)


!   Handling of unconverged points
    if (op%converged) then
      if (is_out_lier (drag_statistics(i), op%cd)) then
        op%converged = .false.
        if (show_details) call print_colored (COLOR_WARNING, 'flip')
      else if (cl_changed (op_spec%spec_cl, op_spec%value, op%cl)) then
        op%converged = .false.
        if (show_details) call print_colored (COLOR_WARNING, 'lift')
        if (show_details) write (*,'(A)',advance = 'no') 'lift'
      end if 
    end if

    if (.not. op%converged .and. xfoil_options%fix_unconverged) then

      if (show_details) write (*,'(A)',advance = 'no') '['

!     Try to initialize BL at intermediate new point (in the direction away from stall)
      tmp_op_spec = op_spec
      if (op_spec%spec_cl) then
        tmp_op_spec%value = op_spec%value - 0.02d0
        if (tmp_op_spec%value == 0.d0) tmp_op_spec%value = 0.01d0       !because of Type 2 polar calc
      else
        tmp_op_spec%value = op_spec%value - 0.25d0
      end if

      ! init BL for this new point to start for fix with little increased Re
      tmp_op_spec%re%number = tmp_op_spec%re%number * 1.001d0
      call xfoil_init_BL (show_details .and. (.not. xfoil_options%reinitialize))
      call run_op_point  (tmp_op_spec, &
                          xfoil_options%viscous_mode, xfoil_options%maxit, show_details , & 
                          op)

!     Now try to run again at the old operating point increasing RE a little ...

      iretry = 1
      nretry = 3
      point_fixed = .false.

      do while (.not. point_fixed .and. (iretry <= nretry)) 

        op_spec%re%number = op_spec%re%number * 1.002d0

        if (xfoil_options%reinitialize) call xfoil_init_BL (.false.)

        call run_op_point (op_spec, &
                           xfoil_options%viscous_mode, xfoil_options%maxit, show_details, & 
                          op)
                              
        if (.not. op%converged    & 
            .or. (is_out_lier (drag_statistics(i), op%cd))  &
            .or. (cl_changed (op_spec%spec_cl, op_spec%value, op%cl))) then 

        ! Re-init the second try
          call xfoil_init_BL (show_details .and. (.not. xfoil_options%reinitialize))

        else 
          point_fixed = .true.
        end if 

        iretry = iretry + 1

      end do 

      if(show_details) then 
        write (*,'(A)',advance = 'no') ']'
        if (point_fixed) then 
          call print_colored (COLOR_NOTE, 'fixed')
        else
          call print_colored (COLOR_ERROR,  'x')
        end if  
      end if 

!     no fix achieved - reinit BL (for the next op) - set converged flag to .false.
      if(.not. point_fixed) then
        if (.not. xfoil_options%reinitialize) call xfoil_init_BL (show_details)
        op%converged = .false.
      end if
    end if

    op_points_result(i) = op

!   early exit if not converged for speed optimization 
    if ((.not. op%converged) .and. xfoil_options%exit_if_unconverged) then 
      exit
    end if 


  end do 


! Print warnings about unconverged points
!        Update statistics

  if(show_details) write (*,*) 

  do i = 1, noppoint

    op = op_points_result(i)   
    if (op%converged) then 
      if (.not. is_out_lier (drag_statistics(i), op%cd)) then 
        call update_statistic (drag_statistics(i), op%cd)
      end if 

      ! jx-mod Support Type 1 and 2 re numbers - cl may not be negative  
      if ((op_spec%re%type == 2) .and. (op%cl <= 0d0)) then 
        write (*,*)
        write(*,'(15x,A,I2,A, F6.2)') "Warning: Negative lift for Re-Type 2 at" // &
        " op",i," - cl:",op%cl
      end if 
    end if 

  end do
  
end subroutine run_op_points

  

!===============================================================================
!
! Runs Xfoil at a specified op_point which is either
!  - at an angle of attack
!  - at an lift coefficient
!
! Assumes airfoil geometry, reynolds number, and mach number have already been 
! set in Xfoil.
!
!===============================================================================

subroutine run_op_point (op_point_spec,        &
                         viscous_mode, maxit, show_details,  &
                         op_point_result)

  use xfoil_inc
  use os_util

  type(op_point_specification_type), intent(in)  :: op_point_spec
  logical,                           intent(in)  :: viscous_mode, show_details
  integer,                           intent(in)  :: maxit
  type(op_point_result_type),        intent(out) :: op_point_result

  integer       :: niter_needed  
  character(20) :: outstring 

  op_point_result%cl    = 0.d0
  op_point_result%cd    = 0.d0
  op_point_result%alpha = 0.d0
  op_point_result%cm    = 0.d0
  op_point_result%xtrt  = 0.d0
  op_point_result%xtrb  = 0.d0
  op_point_result%converged = .true.

! Support Type 1 and 2 re numbers  
  REINF1 = op_point_spec%re%number
  RETYP  = op_point_spec%re%type 
  MATYP  = op_point_spec%ma%type 
  call MINFSET(op_point_spec%ma%number)

! Set compressibility parameters from MINF
  CALL COMSET

! Set ncrit per point
  ACRIT = op_point_spec%ncrit

! Inviscid calculations for specified cl or alpha
  if (op_point_spec%spec_cl) then
    LALFA = .FALSE.
    ALFA = 0.d0
    CLSPEC = op_point_spec%value
    call SPECCL
  else 
    LALFA = .TRUE.
    ALFA = op_point_spec%value * DTOR
    call SPECAL
  end if

  if (abs(ALFA-AWAKE) .GT. 1.0E-5) LWAKE  = .false.
  if (abs(ALFA-AVISC) .GT. 1.0E-5) LVCONV = .false.
  if (abs(MINF-MVISC) .GT. 1.0E-5) LVCONV = .false.

  ! Viscous calculations (if requested)

  op_point_result%converged = .true. 

  if (viscous_mode) then 
    
    call VISCAL(maxit, niter_needed)

    ! coverged? 

    if (niter_needed > maxit) then 
      op_point_result%converged = .false.
    ! RMSBL equals to viscrms() formerly used...
    else if (.not. LVCONV .or. (RMSBL > 1.D-4)) then 
      op_point_result%converged = .false.
    else 
      op_point_result%converged = .true.
    end if

  end if
   
  ! Outputs

  op_point_result%cl    = CL
  op_point_result%cm    = CM
  op_point_result%alpha = ALFA/DTOR

  if (viscous_mode) then 
    op_point_result%cd   = CD
    op_point_result%xtrt = XOCTR(1)
    op_point_result%xtrb = XOCTR(2)
    if (op_point_result%converged) &
      call detect_bubble (op_point_result%bubblet, op_point_result%bubbleb)
  else
    op_point_result%cd   = CDP
    op_point_result%xtrt = 0.d0
    op_point_result%xtrb = 0.d0
    op_point_result%bubblet%found = .false.
    op_point_result%bubbleb%found = .false.
  end if

! Final check for NaNs

  if (isnan(op_point_result%cl)) then
    op_point_result%cl = -1.D+08
    op_point_result%converged = .false.
  end if
  if (isnan(op_point_result%cd)) then
    op_point_result%cd = 1.D+08
    op_point_result%converged = .false.
  end if
  if (isnan(op_point_result%cm)) then
    op_point_result%cm = -1.D+08
    op_point_result%converged = .false.
  end if

  if(show_details) then 
!   write (outstring,'(I4)') niter_needed
    if (op_point_result%converged) then
!     call print_colored (COLOR_NORMAL,  ' ' // trim(adjustl(outstring)))
      call print_colored (COLOR_NORMAL,  '.')
    else
!     call print_colored (COLOR_WARNING, ' ' // trim(adjustl(outstring)))
      call print_colored (COLOR_WARNING, 'x')
    end if
  end if

end subroutine run_op_point


!-------------------------------------------------------------------------------
! #exp-bubble
! Detect a bubble on top or bottom side using xfoil TAU (shear stress) info
!    
!       If TAU < 0 and end of laminar separation is before transition point 
!       it should be a bubble
! 
! Code is inspired from Enno Eyb / xoper.f from xfoil source code
!-------------------------------------------------------------------------------

subroutine detect_bubble (bubblet, bubbleb)

  use xfoil_inc

  type (bubble_type), intent(inout) :: bubblet, bubbleb
  double precision :: CF 
  double precision :: detect_xstart, detect_xend 
  integer :: I, IS, IBL
    
  bubblet%found  = .false.
  bubblet%xstart = 0d0
  bubblet%xend   = 0d0

  bubbleb%found  = .false.
  bubbleb%xstart = 0d0
  bubbleb%xend   = 0d0

  detect_xstart = 0.05d0              ! detection range 
  detect_xend   = 1d0
  

  !!Write CF to file together with results
  !open  (unit=iunit, file='CF.txt')
  ! write(*,'(A)') '    X       Y       CF'

! Detect range on upper/lower side where shear stress < 0 

! --- This is the Original stripped down from XFOIL 
  DO I=1, N

    if((X(I) >= detect_xstart) .and. (X(I) <= detect_xend)) then

      IS = 1
      IF(GAM(I) .LT. 0.0) IS = 2
    
      IF(LIPAN .AND. LVISC) THEN        ! bl calc done and viscous mode? 
        IF(IS.EQ.1) THEN
          IBL = IBLTE(IS) - I + 1
        ELSE
          IBL = IBLTE(IS) + I - N
        ENDIF
        CF =  TAU(IBL,IS)/(0.5*QINF**2)
      ELSE
        CF = 0.
      ENDIF
  ! --- End Original stripped down from XFOIL 

      if (IS == 1) then                 ! top side - going from TE to LE 
        if ((X(I) <= XOCTR(1)) .and. (.not.bubblet%found) )  then  ! no bubbles after transition point
          if     ((CF < 0d0) .and. (bubblet%xend == 0d0)) then
            bubblet%xend = X(I) 
          elseif ((CF < 0d0) .and. (bubblet%xend > 0d0)) then 
            bubblet%xstart   = X(I) 
          elseif ((CF >= 0d0) .and. (bubblet%xstart > 0d0)) then 
            bubblet%found = .true.
          else
          end if 
        end if 
      else                              ! bottom side - going from LE to TE 
        if((X(I) <= XOCTR(2)) .and. (.not.bubblet%found) )  then      ! no bubbles after transition point
          if     ((CF < 0d0) .and. (bubbleb%xstart == 0d0)) then
            bubbleb%xstart = X(I) 
          elseif ((CF < 0d0) .and. (bubbleb%xstart > 0d0)) then 
            bubbleb%xend   = X(I) 
          elseif ((CF >= 0d0) .and. (bubbleb%xend > 0d0)) then 
            bubbleb%found = .true.
          else
          end if 
        end if  
      end if  
    
      ! write(*,'(3F14.6)') X(I), Y(I), CF
    end if 

  ENDDO		

  if ((bubblet%xstart > 0d0) .and. (bubblet%xend == 0d0)) then 
    bubblet%xend = XOCTR(1)
    bubblet%found  = .true.
  end if
  if ((bubbleb%xstart > 0d0) .and. (bubbleb%xend == 0d0)) then 
    bubbleb%xend = XOCTR(2)
    bubbleb%found  = .true.
  end if
 
  ! write (*,*) 
  ! if (bubblet%found)  &
  ! write (*,'(A,L,3(3x,F6.4))') '   -- Top ', & 
  !                          bubblet%found, bubblet%xstart, bubblet%xend, XOCTR(1)
  !if (bubbleb%found)  &
  !  write (*,'(A,L,3(3x,F6.4))') '   -- Bot ', &
  !                          bubbleb%found, bubbleb%xstart, bubbleb%xend, XOCTR(2)
   !close (iunit)
  
  return

end subroutine detect_bubble
  


!=============================================================================80
!
! Subroutine to smooth an airfoil using Xfoil's PANGEN subroutine
!
!=============================================================================80
subroutine smooth_paneling(foilin, npoint, foilout, opt_geom_options)

  use xfoil_inc
  use vardef, only : airfoil_type

  type(airfoil_type), intent(in) :: foilin
  integer, intent(in) :: npoint
  type(airfoil_type), intent(out) :: foilout
  type(xfoil_geom_options_type), intent(in), optional :: opt_geom_options

  type(xfoil_geom_options_type) :: geom_options
  integer :: i
  logical :: needs_cleanup

! Some things that need to be allocated for XFoil PANGEN

  needs_cleanup = .false.
  if (.not. allocated(W1)) then
    allocate(W1(6*IQX))
    allocate(W2(6*IQX))
    allocate(W3(6*IQX))
    allocate(W4(6*IQX))
    allocate(W5(6*IQX))
    allocate(W6(6*IQX))
    needs_cleanup = .true.
  end if

! Set some things that Xfoil may need to do paneling

  PI = 4.d0*atan(1.d0)
  HOPI = 0.5d0/PI
  QOPI = 0.25d0/PI
  SIG(:) = 0.d0
  NW = 0
  AWAKE = 0.d0
  LWDIJ = .false.
  LIPAN = .false.
  LBLINI = .false.
  WAKLEN = 1.d0
  GAM(:) = 0.d0
  SIGTE = 0.d0
  GAMTE = 0.d0
  SIGTE_A = 0.d0
  GAMTE_A = 0.d0
  SILENT_MODE = .TRUE.

  ! Set geometry options for output airfoil

  if (.not. present (opt_geom_options)) then 
    ! set xoptfoil standard values 
    geom_options%npan = npoint
    geom_options%cvpar = 1.d0
  ! jx-mod If set to geom_options%cterat = 0.15d0 the curvature at TE panel
  !     tends to flip away and have tripple value (bug in xfoil) 
  !     with a very small value the panel gets wider and the quality better
    geom_options%cterat = 0.0d0
    geom_options%ctrrat = 0.2d0
    geom_options%xsref1 = 1.d0
    geom_options%xsref2 = 1.d0
    geom_options%xpref1 = 1.d0
    geom_options%xpref2 = 1.d0
  else 
    geom_options = opt_geom_options
    ! npoint overwrites if set 
    if (npoint > 0) geom_options%npan = npoint
  end if 

! Set xfoil airfoil and paneling options

  call xfoil_set_airfoil(foilin)
  call xfoil_set_paneling(geom_options)

! Smooth paneling with PANGEN

  call PANGEN(.NOT. SILENT_MODE)

! Put smoothed airfoil coordinates into derived type

  foilout%npoint = geom_options%npan
  allocate(foilout%x(foilout%npoint))
  allocate(foilout%z(foilout%npoint))
  do i = 1, foilout%npoint
    foilout%x(i) = X(i)
    foilout%z(i) = Y(i)
  end do

! Deallocate memory that is not needed anymore

  if (needs_cleanup) then
    deallocate(W1)
    deallocate(W2)
    deallocate(W3)
    deallocate(W4)
    deallocate(W5)
    deallocate(W6)
  end if
  
end subroutine smooth_paneling

!=============================================================================80
!
! Subroutine to apply a flap deflection to the buffer airfoil and set it as the
! current airfoil.  For best results, this should be called after PANGEN.
!
!=============================================================================80
subroutine xfoil_apply_flap_deflection(flap_spec, degrees)

  use xfoil_inc
  use vardef,     only : flap_spec_type        
 
  type(flap_spec_type),   intent(in) :: flap_spec

  double precision, intent(in) :: degrees
  
  integer y_flap_spec_int

  if (flap_spec%y_flap_spec == 'y/c') then
    y_flap_spec_int = 0
  else
    y_flap_spec_int = 1
  end if

! Apply flap deflection

  ! caution: FLAP will change y_flap a little --> ()
  call FLAP((flap_spec%x_flap), (flap_spec%y_flap), y_flap_spec_int, degrees)

end subroutine xfoil_apply_flap_deflection


!=============================================================================80
!
! Allocates xfoil variables that may be too big for the stack in OpenMP
!
!=============================================================================80
subroutine xfoil_init()

  use xfoil_inc

! Allocate variables that may be too big for the stack in OpenMP

  allocate(AIJ(IQX,IQX))
  allocate(BIJ(IQX,IZX))
  allocate(DIJ(IZX,IZX))
  allocate(CIJ(IWX,IQX))
  allocate(IPAN(IVX,ISX))
  allocate(ISYS(IVX,ISX))
  allocate(W1(6*IQX))
  allocate(W2(6*IQX))
  allocate(W3(6*IQX))
  allocate(W4(6*IQX))
  allocate(W5(6*IQX))
  allocate(W6(6*IQX))
  allocate(VTI(IVX,ISX))
  allocate(XSSI(IVX,ISX))
  allocate(UINV(IVX,ISX))
  allocate(UINV_A(IVX,ISX))
  allocate(UEDG(IVX,ISX))
  allocate(THET(IVX,ISX))
  allocate(DSTR(IVX,ISX))
  allocate(CTAU(IVX,ISX))
  allocate(MASS(IVX,ISX))
  allocate(TAU(IVX,ISX))
  allocate(DIS(IVX,ISX))
  allocate(CTQ(IVX,ISX))
  allocate(DELT(IVX,ISX))
  allocate(TSTR(IVX,ISX))
  allocate(USLP(IVX,ISX))
  allocate(VM(3,IZX,IZX))
  allocate(VA(3,2,IZX))
  allocate(VB(3,2,IZX))
  allocate(VDEL(3,2,IZX))

end subroutine xfoil_init

!=============================================================================80
!
! Initializes xfoil variables
!
!=============================================================================80
subroutine xfoil_defaults(xfoil_options)

  use xfoil_inc

  type(xfoil_options_type), intent(in) :: xfoil_options

  N = 0
  SILENT_MODE = xfoil_options%silent_mode
  PI = 4.d0*atan(1.d0)
  HOPI = 0.5d0/PI
  QOPI = 0.25d0/PI
  DTOR = PI/180.d0
  QINF = 1.d0
  SIG(:) = 0.d0
  QF0(:) = 0.d0
  QF1(:) = 0.d0
  QF2(:) = 0.d0
  QF3(:) = 0.d0
  NW = 0
  RETYP = 1
  MATYP = 1
  GAMMA = 1.4d0
  GAMM1 = GAMMA - 1.d0
  XCMREF = 0.25d0
  YCMREF = 0.d0
  LVISC = xfoil_options%viscous_mode
  AWAKE = 0.d0
  AVISC = 0.d0
  ITMAX = xfoil_options%maxit
  LWDIJ = .false.
  LIPAN = .false.
  LBLINI = .false.
  ACRIT = xfoil_options%ncrit
  IDAMP = 0
  XSTRIP(1) = xfoil_options%xtript
  XSTRIP(2) = xfoil_options%xtripb
  VACCEL = xfoil_options%vaccel
  WAKLEN = 1.d0
  PSIO = 0.d0
  GAMU(:,:) = 0.d0
  GAM(:) = 0.d0
  SIGTE = 0.d0
  GAMTE = 0.d0
  SIGTE_A = 0.d0
  GAMTE_A = 0.d0
  APANEL(:) = 0.d0

! Set boundary layer calibration parameters

  call BLPINI

end subroutine xfoil_defaults

!=============================================================================80
!
! Sets airfoil for xfoil into buffer and current airfoil
!
!=============================================================================80
subroutine xfoil_set_airfoil(foil)

  use xfoil_inc, only : XB, YB, NB, SB, XBP, YBP 
  use vardef,    only : airfoil_type
  type(airfoil_type), intent(in) :: foil

! Set foil into xfoil buffer foil
  NB = foil%npoint
  XB(1:NB) = foil%x
  YB(1:NB) = foil%z

  CALL SCALC(XB,YB,SB,NB)
  CALL SEGSPL(XB,XBP,SB,NB)
  CALL SEGSPL(YB,YBP,SB,NB)

! Also copy buffer airfoil to xfoil current foil. This is also made in PANGEN -
!        ... but PANGEN shouldn't always be called before xfoil calculations
  call ABCOPY (.true.)

end subroutine xfoil_set_airfoil


!=============================================================================80
!
! Sets xfoil paneling options
!
!=============================================================================80
subroutine xfoil_set_paneling(geom_options)

  use xfoil_inc, only : NPAN, CVPAR, CTERAT, CTRRAT, XSREF1, XSREF2, XPREF1,   &
                        XPREF2

  type(xfoil_geom_options_type), intent(in) :: geom_options

  NPAN = geom_options%npan
  CVPAR = geom_options%cvpar
  CTERAT = geom_options%cterat
  CTRRAT = geom_options%ctrrat
  XSREF1 = geom_options%xsref1
  XSREF2 = geom_options%xsref2
  XPREF1 = geom_options%xpref1
  XPREF2 = geom_options%xpref2
  
end subroutine xfoil_set_paneling

!=============================================================================80
!
! Deallocates memory in xfoil
!
!=============================================================================80
subroutine xfoil_cleanup()

  use xfoil_inc

! Deallocate variables

  deallocate(AIJ)
  deallocate(BIJ)
  deallocate(DIJ)
  deallocate(CIJ)
  deallocate(IPAN)
  deallocate(ISYS)
  deallocate(W1)
  deallocate(W2)
  deallocate(W3)
  deallocate(W4)
  deallocate(W5)
  deallocate(W6)
  deallocate(VTI)
  deallocate(XSSI)
  deallocate(UINV)
  deallocate(UINV_A)
  deallocate(UEDG)
  deallocate(THET)
  deallocate(DSTR)
  deallocate(CTAU)
  deallocate(MASS)
  deallocate(TAU)
  deallocate(DIS)
  deallocate(CTQ)
  deallocate(DELT)
  deallocate(TSTR)
  deallocate(USLP)
  deallocate(VM)
  deallocate(VA)
  deallocate(VB)
  deallocate(VDEL)

end subroutine xfoil_cleanup


!------------------------------------------------------------------------------
!
! jx-mod xfoil extensions
!
!------------------------------------------------------------------------------

!------------------------------------------------------------------------------
! Retrieve AMAX from Xfoil  
!     PANGEN or ABCOPY has to be done first to have the value calculated
!------------------------------------------------------------------------------

function xfoil_geometry_amax()

  use xfoil_inc, only : AMAX
  double precision :: xfoil_geometry_amax

  xfoil_geometry_amax = AMAX

end function xfoil_geometry_amax

!------------------------------------------------------------------------------
! Reset xfoil_driver e.g. for an new polar 
!------------------------------------------------------------------------------
subroutine xfoil_driver_reset ()

  if (allocated(drag_statistics))  deallocate (drag_statistics)

end subroutine xfoil_driver_reset 

!------------------------------------------------------------------------------
! Init Boundary layer of xfoil viscous calculation  
!------------------------------------------------------------------------------
subroutine xfoil_init_BL (show_details)

  use xfoil_inc, only : LIPAN, LBLINI
  use os_util, only: print_colored, COLOR_NOTE

  logical, intent(in) :: show_details

  LIPAN  = .false.
  LBLINI = .false.

  if(show_details) call print_colored (COLOR_NOTE, 'i')

end subroutine xfoil_init_BL 

!------------------------------------------------------------------------------
! Scale max thickness and camber and their positions of foil 
!        using xfoil THKCAM and HIPNT
!
!   f_thick  - scaling factor for thickness
!   d xthick - delta x for max thickness x-position
!   f_camb   - scaling factor for camber
!   d_xcamb  - delta x for max camber position
!
! 
! ** Note ** 
!
! Before calling this subroutine, "smooth_paneling()" (which uses xfoil PANGEN)
! should be done on foil to avoid strange artefacts at the leading edge.
! XFOIL>HIPNT (moving thickness highpoint) is very sensible and behaves badly
! if the LE curvature does not fit to the spline algorithm
!------------------------------------------------------------------------------
subroutine xfoil_scale_thickness_camber (infoil, f_thick, d_xthick, f_camb, d_xcamb, outfoil)

  use xfoil_inc, only : AIJ
  use vardef,    only : airfoil_type

  type(airfoil_type), intent(in)  :: infoil
  type(airfoil_type), intent(out) :: outfoil
  double precision, intent(in) :: f_thick, d_xthick, f_camb, d_xcamb
  double precision :: thick, xthick, camb, xcamb

! Check to make sure xfoil is initialized
  if (.not. allocated(AIJ)) then
    write(*,*) "Error: xfoil is not initialized!  Call xfoil_init() first."
    stop
  end if
! Set xfoil airfoil and prepare globals, get current thickness
  call xfoil_set_airfoil (infoil)
  call xfoil_get_geometry_info  (thick, xthick, camb, xcamb) 


! Run xfoil to change thickness and camber and positions

  IF ((d_xcamb /= 0.d0) .or. (d_xthick /= 0.d0))  &
    call HIPNT  (xcamb + d_xcamb, xthick + d_xthick)
  IF ((f_thick /= 1.d0) .or. (f_camb /= 1.d0))  &
    call THKCAM (f_thick, f_camb)

                
! retrieve outfoil from xfoil buffer

  call xfoil_reload_airfoil(outfoil)

end subroutine xfoil_scale_thickness_camber

!------------------------------------------------------------------------------
! Set max thickness and camber and their positions of foil 
!        using xfoil THKCAM and HIPNT
!
!   maxt  - new thickness
!   xmaxt - new max thickness x-position
!   maxc  - new camber
!   xmaxc - new max camber position
!
!   if one of the values = 0.0 then this value is not set
! 
! ** Note ** 
!
! Before calling this subroutine, "smooth_paneling()" (which uses xfoil PANGEN)
! should be done on foil to avoid strange artefacts at the leading edge.
! XFOIL>HIPNT (moving thickness highpoint) is very sensible and behaves badly
! if the LE curvature does not fit to the spline algorithm
!------------------------------------------------------------------------------
subroutine xfoil_set_thickness_camber (infoil, maxt, xmaxt, maxc, xmaxc, outfoil)

  use xfoil_inc, only : AIJ
  use vardef,    only : airfoil_type

  type(airfoil_type), intent(in)  :: infoil
  type(airfoil_type), intent(out) :: outfoil

  double precision, intent(in) :: maxt, xmaxt, maxc, xmaxc
  double precision :: CFAC,TFAC, thick, xthick, camb, xcamb

! Check to make sure xfoil is initialized
  if (.not. allocated(AIJ)) then
    write(*,*) "Error: xfoil is not initialized!  Call xfoil_init() first."
    stop
  end if

! Set xfoil airfoil and prepare globals, get current thickness
  call xfoil_set_airfoil (infoil)
  call xfoil_get_geometry_info  (thick, xthick, camb, xcamb) 

! Run xfoil to change thickness and camber 
  CFAC = 1.0
  TFAC = 1.0

  if (maxc > 0.0d0) then
    IF(camb .NE.0.0 .AND. maxc.NE.999.0) CFAC = maxc / camb
  end if
  if (maxt > 0.0d0) then
    IF(thick.NE.0.0 .AND. maxt.NE.999.0) TFAC = maxt / thick
  end if 

  call THKCAM ( TFAC, CFAC)

! Run xfoil to change highpoint of thickness and camber 

  if((xmaxc > 0d0) .and. (xmaxt > 0d0)) then
    call HIPNT (xmaxc, xmaxt)
  elseif((xmaxc > 0d0) .and. (xmaxt == 0d0)) then
    call HIPNT (xmaxc, xthick)
  elseif((xmaxc == 0d0) .and. (xmaxt > 0d0)) then
    call HIPNT (xcamb, xmaxt)
  end if 

! Recalc values ...
  call xfoil_get_geometry_info (thick, xthick, camb, xcamb) 

! retrieve outfoil from xfoil buffer
  call xfoil_reload_airfoil(outfoil)

end subroutine xfoil_set_thickness_camber



!------------------------------------------------------------------------------
! Scale LE radius 
!        using xfoil LERAD
! In:
!   infoil      - foil to scale LE
!   f_radius    - scaling factor for LE radius
!   x_blend     - blending distance/c from LE
! Out:
!   new_radius  - new LE radius
!   outfoil     = modified foil
! 
! ** Note ** 
!
! Before calling this subroutine, "smooth_paneling()" (which uses xfoil PANGEN)
! should be done on foil to avoid strange artefacts at the leading edge.
!------------------------------------------------------------------------------
subroutine xfoil_scale_LE_radius (infoil, f_radius, x_blend, outfoil)

  use xfoil_inc, only : AIJ, RADBLE
  use vardef,    only : airfoil_type

  type(airfoil_type), intent(in)  :: infoil
  double precision, intent(in) :: f_radius, x_blend
  double precision  :: new_radius
  type(airfoil_type), intent(out) :: outfoil

! Check to make sure xfoil is initialized
  if (.not. allocated(AIJ)) then
    write(*,*) "Error: xfoil is not initialized!  Call xfoil_init() first."
    stop
  end if

! Set xfoil airfoil and prepare globals, get current thickness
  call xfoil_set_airfoil (infoil)

! Run xfoil to change thickness and camber and positions
  IF ((f_radius /= 1.d0))  call LERAD (f_radius,x_blend, new_radius) 

! Update xfoil globals
  RADBLE = new_radius

  call xfoil_reload_airfoil(outfoil)

end subroutine xfoil_scale_LE_radius


!-------------------------------------------------------------------------
! gets buffer airfoil thickness, camber .. positions
!-------------------------------------------------------------------------
subroutine xfoil_get_geometry_info (maxt, xmaxt, maxc, xmaxc) 
 
  use xfoil_inc
  Real*8, intent(out) :: maxt, xmaxt, maxc, xmaxc
  Real*8 :: TYMAX
  
!--- find the current buffer airfoil camber and thickness
  CALL GETCAM(XCM,YCM,NCM,XTK,YTK,NTK,                  &
              XB,XBP,YB,YBP,SB,NB )
  CALL GETMAX(XCM,YCM,YCMP,NCM,xmaxc,maxc)
  CALL GETMAX(XTK,YTK,YTKP,NTK,xmaxt,TYMAX)

  maxt = 2.0 * TYMAX

end subroutine xfoil_get_geometry_info



!-------------------------------------------------------------------------
! Reloads airfoil from xfoil buffer foil
!-------------------------------------------------------------------------
subroutine xfoil_reload_airfoil(foil)

  use xfoil_inc, only : XB, YB, NB
  use vardef,    only : airfoil_type

  type(airfoil_type), intent(inout) :: foil

  if (allocated (foil%x))  deallocate (foil%x)
  if (allocated (foil%z))  deallocate (foil%z)
  allocate(foil%x(NB))
  allocate(foil%z(NB))

  foil%npoint = NB
  foil%x = XB(1:NB)
  foil%z = YB(1:NB)
  
end subroutine xfoil_reload_airfoil

!--JX-mod  --------------------------------------------------------------------
! 
!  Toolfunctions to handle out lier (flip) detection of drag and lift 
!
!------------------------------------------------------------------------------

subroutine init_statistics (npoints, value_statistics)

  type ( value_statistics_type), dimension (:), allocatable, intent (inout) :: value_statistics
  integer, intent (in) :: npoints 
  integer :: i
  
  if (allocated(value_statistics))  deallocate (value_statistics)

  allocate (value_statistics(npoints))
  do i = 1, npoints
    value_statistics(i)%nvalue   = 0
    value_statistics(i)%no_check = .false.
    value_statistics(i)%minval   = 0.d0
    value_statistics(i)%maxval   = 0.d0
    value_statistics(i)%meanval  = 0.d0
  end do 

end subroutine init_statistics
!------------------------------------------------------------------------------
subroutine update_statistic (value_statistic, new_value)

  type ( value_statistics_type), intent (inout) :: value_statistic
  doubleprecision, intent (in) :: new_value 
  
  value_statistic%minval  = min (value_statistic%minval, new_value) 
  value_statistic%maxval  = max (value_statistic%maxval, new_value)
  value_statistic%meanval = (value_statistic%meanval * value_statistic%nvalue + new_value) / &
                            (value_statistic%nvalue + 1)
  value_statistic%nvalue  = value_statistic%nvalue + 1

end subroutine update_statistic

!------------------------------------------------------------------------------
function is_out_lier (value_statistic, check_value)

  type ( value_statistics_type), intent (in) :: value_statistic
  doubleprecision, intent (in) :: check_value
  logical :: is_out_lier 
  doubleprecision :: out_lier_tolerance, value_tolerance

  is_out_lier = .false. 
  out_lier_tolerance = 0.4

  if(value_statistic%nvalue > 0 .and. (.not. value_statistic%no_check)) then           !do we have enough values to check? 

    value_tolerance    = abs(check_value - value_statistic%meanval)/max(0.0001d0, value_statistic%meanval) 
    is_out_lier = (value_tolerance > out_lier_tolerance )  

  end if 

end function is_out_lier

!------------------------------------------------------------------------------
subroutine show_out_lier (ipoint, value_statistic, check_value)

  type ( value_statistics_type), intent (in) :: value_statistic
  doubleprecision, intent (in) :: check_value
  integer, intent (in) :: ipoint

  write (*,'( 30x, A,A,I2,A,F8.6, A,F8.6)') 'Out lier - ', 'op', ipoint, ": ", check_value, & 
              '    meanvalue: ', value_statistic%meanval

end subroutine show_out_lier


!----Check if lift has changed although it should be fix with spec_cl ---------
function cl_changed (spec_cl, op_point, cl)

  doubleprecision, intent (in) :: op_point, cl
  logical, intent (in) :: spec_cl
  logical :: cl_changed

  if (spec_cl .and. (abs(cl - op_point) > 0.01d0)) then
    cl_changed = .true.
  else
    cl_changed = .false.
  end if 

end function cl_changed

end module xfoil_driver



