document.addEventListener('DOMContentLoaded', function() {
    // Language Switch Functionality
    const currentPage = window.location.pathname.split('/').pop();
    const langBtn = document.querySelector('.lang-btn');
    
    if (currentPage === 'index.html' || currentPage === '') {
        // We're on the Russian page
        if (langBtn) {
            langBtn.classList.remove('active');
        }
    } else if (currentPage === 'index-en.html') {
        // We're on the English page
        if (langBtn) {
            langBtn.classList.add('active');
        }
    }
    // Mobile Menu Toggle
    const menuToggle = document.querySelector('.menu-toggle');
    const nav = document.querySelector('nav');

    if (menuToggle) {
        menuToggle.addEventListener('click', function() {
            nav.style.display = nav.style.display === 'block' ? 'none' : 'block';
            menuToggle.classList.toggle('active');
        });
    }

    // Smooth Scrolling for Anchor Links
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function(e) {
            e.preventDefault();
            const target = document.querySelector(this.getAttribute('href'));
            if (target) {
                window.scrollTo({
                    top: target.offsetTop - 80,
                    behavior: 'smooth'
                });
            }
        });
    });

    // Accordion Functionality
    const accordionItems = document.querySelectorAll('.accordion-item');
    
    accordionItems.forEach(item => {
        const header = item.querySelector('.accordion-header');
        
        header.addEventListener('click', () => {
            // Close all other accordion items
            accordionItems.forEach(otherItem => {
                if (otherItem !== item && otherItem.classList.contains('active')) {
                    otherItem.classList.remove('active');
                }
            });
            
            // Toggle current accordion item
            item.classList.toggle('active');
        });
    });

    // Tab Functionality
    const tabHeaders = document.querySelectorAll('.tab-header');
    const tabContents = document.querySelectorAll('.tab-content');
    
    tabHeaders.forEach(header => {
        header.addEventListener('click', () => {
            // Remove active class from all headers and contents
            tabHeaders.forEach(h => h.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));
            
            // Add active class to clicked header
            header.classList.add('active');
            
            // Add active class to corresponding content
            const tabId = header.getAttribute('data-tab');
            document.getElementById(tabId).classList.add('active');
        });
    });

    // Form Submission
    const contactForm = document.getElementById('contactForm');
    
    if (contactForm) {
        contactForm.addEventListener('submit', function(e) {
            e.preventDefault();
            
            // Get form values
            const name = document.getElementById('name').value;
            const email = document.getElementById('email').value;
            const company = document.getElementById('company').value;
            const message = document.getElementById('message').value;
            
            // Here you would typically send the form data to a server
            // For demonstration, we'll just show a success message
            alert('Thank you for your message! We will get back to you soon.');
            
            // Reset form
            contactForm.reset();
        });
    }

    // Animation on Scroll
    function animateOnScroll() {
        const elements = document.querySelectorAll('.animate-on-scroll');
        
        elements.forEach(element => {
            const elementPosition = element.getBoundingClientRect().top;
            const windowHeight = window.innerHeight;
            
            if (elementPosition < windowHeight - 100) {
                element.classList.add('animated');
            }
        });
    }
    
    // Add animate-on-scroll class to elements
    document.querySelectorAll('section h2, .accordion-item, .tab-content, .contact-form').forEach(element => {
        element.classList.add('animate-on-scroll');
    });
    
    // Initial check for animations
    animateOnScroll();
    
    // Check for animations on scroll
    window.addEventListener('scroll', animateOnScroll);
});